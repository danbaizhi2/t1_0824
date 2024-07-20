# encoding: utf-8

import struct
import time
import hmac
import base64
import hashlib
import traceback
import sys
import copy
import threading
import json
import pymysql
from flask import Flask
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from flask_compress import Compress
from flask import request
from flask import g
#import MySQLdb

from config import config
from functions.exchange.okx.ouyi_api import api as OuyiAPI
from functions.exchange.okx.risk_cal import RiskCal
from functions.exchange.okx.liquidation import liquidation

from libs.AlarmEngine import Alarm
from libs.LogEngine import Log


class Tools:
    def __init__(self, config):
        self.distribution_config = {
            'distribution_entrust_barcolor_buy_open': {'selected': '#A4FF68', 'not_selected': '#5F8F50'},  # 多开
            'distribution_entrust_barcolor_sell_close': {'selected': '#FF2D2D', 'not_selected': '#8C2632'},  # 多平
            'distribution_entrust_barcolor_sell_open': {'selected': '#FFFF00', 'not_selected': '#FFEBCD'},  # 空开
            'distribution_entrust_barcolor_buy_close': {'selected': '#24B9D6', 'not_selected': '#02708E'},  # 空平
            }
        self.config = config
        self.db_info = self.config['db_info']

    def mysql_short_get(self, sql):
        db = pymysql.connect(user=self.db_info['mysql_user'], password=self.db_info['mysql_password'], host=self.db_info['mysql_host'], port=self.db_info['mysql_port'], db=self.db_info['mysql_db'], charset=self.db_info['mysql_charset'])
        cursor = db.cursor()
        cursor.execute(sql)  # 执行SQL语句
        results = cursor.fetchall()  # 获取所有记录列表
        db.close()

        return results

    def mysql_short_commit(self, sql):
        db = pymysql.connect(user=self.db_info['mysql_user'], password=self.db_info['mysql_password'], host=self.db_info['mysql_host'], port=self.db_info['mysql_port'], db=self.db_info['mysql_db'], charset=self.db_info['mysql_charset'])
        cursor = db.cursor()
        cursor.execute(sql)  # 执行SQL语句
        db.commit()
        db.close()

    def mysql_fetchall(self, db, sql):
        try:
            cursor = db.cursor()
            cursor.execute(sql)
            results = cursor.fetchall()
            cursor.close()
        except:
            print(traceback.format_exc())

            results = []

        return results

    def mysql_execute(self, db, sql):
        try:
            cursor = db.cursor()
            cursor.execute(sql)
            db.commit()
            cursor.close()
        except:
            print(traceback.format_exc())

    def get_price_dict(self):
        # 获取最新价格,保存为字典
        db = pymysql.connect(user=self.db_info['mysql_user'], password=self.db_info['mysql_password'], host=self.db_info['mysql_host'], port=self.db_info['mysql_port'], db=self.db_info['mysql_db'], charset=self.db_info['mysql_charset'])
        cursor = db.cursor()
        sql = "SELECT * FROM price  "
        cursor.execute(sql)  # 执行SQL语句
        results = cursor.fetchall()  # 获取所有记录列表
        db.close()

        dict_price = {}
        for result in results:
            contract_code = result[0]
            price_new = result[1]
            price_index = result[2]
            price_mark = result[3]

            temp_temp_dict = {}
            temp_temp_dict['price_new'] = price_new
            temp_temp_dict['price_index'] = price_index
            temp_temp_dict['price_mark'] = price_mark
            dict_price[contract_code] = temp_temp_dict

        return dict_price

    def get_price(self, dict_price, contract_code, price_type):

        # 调用示例: get_price(dict_price,contract = 'BTC210326',price_type= '市价')
        # 调用示例: get_price(dict_price,contract = 'BTC-USD',price_type= '指数价')
        if price_type == '市价':
            return float(dict_price[contract_code]['price_new'])
        elif price_type == '指数价':
            return float(dict_price[contract_code]['price_index'])
        elif price_type == '标记价':
            return float(dict_price[contract_code]['price_mark'])
        else:
            return float(dict_price[contract_code]['price_new'])

    def get_contract_precision(self, contract):
        try:
            config_server_exchange = self.config['server_exchange']
            config_real_trading = self.config['real_trading']
            config_contracts = self.config['exchange'][config_server_exchange][config_real_trading]['contracts']

            if 'SWAP' in contract:
                round_precision = config_contracts[contract]['round_precision']
            else:
                round_precision = config_contracts[f"{contract.split('-')[0]}-{contract.split('-')[1]}-FUTURES"]['round_precision']

        except:
            round_precision = 1

        return round_precision

    # 转换为显示格式
    def get_display_number(self, number, contract):
        try:
            number = float(number)

            config_server_exchange = self.config['server_exchange']
            config_real_trading = self.config['real_trading']
            config_contracts = self.config['exchange'][config_server_exchange][config_real_trading]['contracts']

            if 'SWAP' in contract:
                display_precision = config_contracts[contract]['display_precision']
            else:
                display_precision = config_contracts[f"{contract.split('-')[0]}-{contract.split('-')[1]}-FUTURES"]['display_precision']

            if 'USDT' in contract:
                number = f'%.{display_precision}f' % round(number / 10000, display_precision) + ' W'
            else:
                unit = 'B' if 'BTC' in contract else 'H'
                number = f'%.{display_precision}f {unit}' % round(number, display_precision)

            # if abs(number) > 1000000000000:
            #     number = str(number/10000)[:5]
            #     if number[-1:] == '.':
            #         number = number[:4]
            #
            #     number = f'{number} WY'
            # elif abs(number) > 100000000:
            #     number = str(number/10000)[:6]
            #     if number[-1:] == '.':
            #         number = number[:5]
            #
            #     number = f'{number} Y'
            # elif abs(number) > 10000:
            #     number = str(number/10000)[:6]
            #     if number[-1:] == '.':
            #         number = number[:5]
            #
            #     number = f'{number} W'
            # else:
            #     number = f'{str(number)[:8]}'

        except:
            pass

        return number


class TypeCheck:
    def __init__(self):
        self.int_min = -1000000
        self.int_max = 1000000
        self.float_min = -1000000
        self.float_max = 1000000
        self.str_max = 15

    def is_int(self, x, border=True):
        x = str(x)

        # 检查字符
        x1 = x
        if str(x1)[:1] == '-':
            x1 = str(x1)[1:]
        elif str(x1)[:1] == '+':
            x1 = str(x1)[1:]
        for _ in str(x1):
            if _ not in ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']:
                msg = f'输入值:"{x}"整数检查不通过'
                # print(msg)
                return False, msg, x

        # 检查边界
        if border:
            x2 = int(float(x))
            if not self.int_min <= x2 <= self.int_max:
                msg = f'输入值:"{x}"超出可输入范围:[{self.int_min}-{self.int_max}]'
                # print(msg)
                return False, msg, x

        # 类型转换
        x4 = x
        try:
            x4 = int(float(x4)) if int(float(x4)) == float(x4) else float(x4)
        except:
            msg = f'输入值:"{x}"无法转换成浮点'
            return False, msg, x4

        return True, '', x4

    def is_posint(self, x, border=True):
        x = str(x)

        # 检查字符
        x1 = x
        if str(x1)[:1] == '-':
            x1 = str(x1)[1:]
        elif str(x1)[:1] == '+':
            x1 = str(x1)[1:]
        for _ in str(x1):
            if _ not in ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']:
                msg = f'输入值:"{x}"整数检查不通过'
                # print(msg)
                return False, msg, x

        # 检查边界
        if border:
            x2 = int(float(x))
            if not 1 <= x2 <= self.int_max:
                msg = f'输入值:"{x}"超出可输入范围:[1-{self.int_max}]'
                # print(msg)
                return False, msg, x

        # 类型转换
        x4 = x
        try:
            x4 = int(float(x4)) if int(float(x4)) == float(x4) else float(x4)
        except:
            msg = f'输入值:"{x}"无法转换成浮点'
            return False, msg, x4

        return True, '', x4

    def is_float(self, x, decimal_place=4):
        x = str(x)

        # 检查字符
        x1 = x
        if str(x1)[:1] == '-':
            x1 = str(x1)[1:]
        elif str(x1)[:1] == '+':
            x1 = str(x1)[1:]
        count_dot = 0
        for _ in str(x1):
            if _ not in ['.', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9']:
                msg = f'输入值:"{x}"小数检查不通过'
                # print(msg)
                return False, msg, x
            if _ == '.':
                count_dot += 1
                if count_dot >= 2:
                    msg = f'输入值:"{x}"中含有多个.'
                    # print(msg)
                    return False, msg, x
        # 检查边界
        x2 = float(x)
        if not self.float_min < x2 < self.float_max:
            msg = f'输入值:"{x}"超出可输入范围:({self.float_min}-{self.float_max})'
            # print(msg)
            return False, msg, x

        # 检查位数
        x3 = x
        if '.' in x3:
            decimal_place2 = len(x3.split('.')[1])
            # print(f'这是小数，小数位数为:{decimal_place}')

            if decimal_place2 > decimal_place:
                msg = f'输入值:"{x}"小数精度超出限制:{decimal_place}位小数'
                return False, msg, x

        # 类型转换
        x4 = x
        try:
            x4 = int(float(x4)) if int(float(x4)) == float(x4) else float(x4)
        except:
            msg = f'输入值:"{x}"无法转换成浮点'
            return False, msg, x4

        return True, '', x4

    def is_posfloat(self, x, decimal_place=4, float_max=1000000):
        x = str(x)

        # 检查字符
        x1 = x
        if str(x1)[:1] == '-':
            x1 = str(x1)[1:]
        elif str(x1)[:1] == '+':
            x1 = str(x1)[1:]
        count_dot = 0
        for _ in str(x1):
            if _ not in ['.', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9']:
                msg = f'输入值:"{x}"小数检查不通过'
                # print(msg)
                return False, msg, x
            if _ == '.':
                count_dot += 1
                if count_dot >= 2:
                    msg = f'输入值:"{x}"中含有多个.'
                    # print(msg)
                    return False, msg, x

        # 检查边界
        x2 = float(x)
        if not 0 < x2 < float_max:
            msg = f'输入值:"{x}"超出可输入范围:(0-{float_max})'
            # print(msg)
            return False, msg, x

        # 检查位数
        x3 = x
        if '.' in x3:
            decimal_place2 = len(x3.split('.')[1])
            # print(f'这是小数，小数位数为:{decimal_place}')

            if decimal_place2 > decimal_place:
                msg = f'输入值:"{x}"小数精度超出限制:{decimal_place}位小数'
                return False, msg, x

        # 类型转换
        x4 = x
        try:
            x4 = int(float(x4)) if int(float(x4)) == float(x4) else float(x4)
        except:
            msg = f'输入值:"{x}"无法转换成浮点'
            return False, msg, x4

        return True, '', x4

    def is_str(self, x, max_len=15):
        x = str(x)

        for x_slice in x:
            if x_slice in ['\'', '\\']:
                return False, f'输入值:"{x}"不能含有: {x_slice}', x

        # 长度检查
        if not 1 <= len(x) <= max_len:
            msg = f'输入值:"{x}"超出位数长度范围:[1-{max_len}]'
            return False, msg, x

        return True, '', x


config_liquidation = config['exchange'][config['server_exchange']][config['real_trading']]['liquidation']
risk_cal = RiskCal(config_liquidation)

compress = Compress()
app = Flask(__name__)
Compress(app)

secret_key = 'SECRET-KEY-KEY5'

request_id_base = time.strftime("%Y%m%d%H%M%S", time.localtime()) + ':'
request_id = 0
request_id_lock = threading.Lock()

# config
mysql_user = config['db_info']['mysql_user']
mysql_password = config['db_info']['mysql_password']
mysql_host = config['db_info']['mysql_host']
mysql_port = config['db_info']['mysql_port']
mysql_db = config['db_info']['mysql_db']
mysql_charset = config['db_info']['mysql_charset']

logger_content = Log(path='./logs/api/api_flask_app_content/', filename='flask_app_content日志', rotating='midnight', backupcount=config['loggerbackupcount'], loggername='logger_content')
logger_performance = Log(path='./logs/api/api_flask_app_performance/', filename='flask_app_performance日志', rotating='midnight', backupcount=config['loggerbackupcount'], loggername='logger_performance')

typecheck = TypeCheck()

tools = Tools(config)
# tool.mysql_short_get(sql)
# tool.mysql_short_commit(sql)


def calGoogleCode(googleKey):
    input = int(time.time()) // 30
    key = base64.b32decode(googleKey)
    msg = struct.pack(">Q", input)
    googleCode = hmac.new(key, msg, hashlib.sha1).digest()
    o = ord(chr(googleCode[19])) & 15
    googleCode = str(
        (struct.unpack(">I", googleCode[o:o + 4])[0] & 0x7fffffff) % 1000000)
    if len(googleCode) == 6:  # 如果验证码的第一位是0，则不会显示。此处判断若是5位码，则在第一位补上0
        googleCode = googleCode
    elif len(googleCode) == 5:
        googleCode = '0' + googleCode
    elif len(googleCode) == 4:
        googleCode = '00' + googleCode
    elif len(googleCode) == 3:
        googleCode = '000' + googleCode
    elif len(googleCode) == 2:
        googleCode = '0000' + googleCode
    elif len(googleCode) == 1:
        googleCode = '00000' + googleCode
    else:
        googleCode = '000000' + googleCode
    return googleCode


def verify_token(token):
    try:
        # 参数为私有秘钥，跟上面方法的秘钥保持一致
        s = Serializer(secret_key)

        # 转换为字典
        temp_dict = s.loads(token)
        # name = temp_dict['name']
        # level = temp_dict['level']

        return temp_dict
    except BaseException:
        return 'token过期'


# 预处理请求数据
@app.before_request
def before_request():

    def new_request_id():
        request_id_lock.acquire()
        global request_id
        request_id += 1
        request_id_lock.release()

        return request_id_base + str(request_id)

    try:
        request_path = request.path
        # 添加请求id
        g.request_id = new_request_id()
        g.request_get_time = time.time()

        # 获取device
        device = 'web' if 'token' in request.cookies else 'app'
        g.device = device
        g.request_path = request_path

        # 清洗输入值
        g.data_in = {}
        data_in = request.form.to_dict()
        for key in data_in:
            g.data_in[key] = str(data_in[key]).replace('－', '-')
            g.data_in[key] = str(g.data_in[key]).replace('＋', '+')

        # 打日志
        logger_content.info({'type': 'request_in', 'request_id': g.request_id, 'device': device, 'url':request.url, 'body': g.data_in})

        token_free_path = [
            '/',
            '/quant/login',
            '/quant/get_info',
        ]

        if request_path not in token_free_path:
            token = request.cookies.get('token') if 'token' not in g.data_in else g.data_in['token']
            verify_result = verify_token(token)

            if verify_result == 'token过期':
                if g.device == 'app':
                    return respond({'code': 1001, 'data': '', 'msg': '登录过期,请重新登录!'})
                else:
                    return respond({'code': 1003, 'data': {
                            'msg': 'token过期'}, 'msg': '登录过期,请重新登录!'})
            # print('verify_result',verify_result)
            g.token = token
            g.level = verify_result['level']
            g.user = verify_result['id']
    except BaseException:
        print(traceback.format_exc())


# 后处理，返回response
def respond(data_out):

    data_out['request_id'] = g.request_id
    if data_out['code'] == 1000:
        data_out['msg_level'] = 'ok'
    elif data_out['code'] == 1001:
        data_out['msg_level'] = 'error'
    else:
        pass

    try:
        # 输出性能日志
        try:
            request_path = request.path
        except BaseException:
            request_path = '--'
        try:
            request_ip = request.remote_addr
        except BaseException:
            request_ip = '--'
        try:
            request_ip_Forwarded = request.headers['X-Forwarded-For']
        except BaseException:
            request_ip_Forwarded = '--'
        try:
            request_handler_time = (time.time() - g.request_get_time) * 1000  # ms
        except BaseException:
            request_handler_time = '--'

        # 输出性能日志
        logger_performance.info({'request_path':request_path, 'request_ip': request_ip, 'request_ip_Forwarded': request_ip_Forwarded, 'request_handler_time': request_handler_time})
        # 打输出业务日志
        if request_path not in ['/quant/trade/get_list_strategy_pro']:
            logger_content.info({'type': 'request_out', 'request_id': g.request_id, 'response': data_out})
    except BaseException:
        pass

    return data_out


# 注册全局异常处理
@app.errorhandler(Exception)
def error_handler(e):

    try:
        print(traceback.format_exc())
        exc_type, exc_value, exc_traceback = sys.exc_info()
        exc_type = str(exc_type.__name__)
        exc_value = str(exc_value)

        error_abstract_inner = exc_type + ':' + exc_value,
    except:
        print(traceback.format_exc())
        error_abstract_inner = ['异常信息获取失败']

    error_abstract_inner2 = error_abstract_inner[0]
    data = {
        "code": 1001,
        "data": '',
        "msg": '接口服务异常||' + error_abstract_inner2 + '||' + '请求id:' + g.request_id,
        'msg_level': 'error',
        "traceback": traceback.format_exc()}

    return respond(data)


@app.route('/')
def index():
    data = {'status': 'server is ok', 'version': 'v1.6.1_1'}
    return respond({'code': 1000, 'data': data, 'msg': '刷新成功'})


# 1.1登录鉴权
@app.route("/quant/login", methods=['POST'])
def quant_login():
    data_in = g.data_in

    in_name = data_in['name']
    in_password = data_in['password']
    in_googlekey = data_in['googlekey']
    in_device = data_in['device']  # 可选值 'web','app'

    def fun_quant_login():
        # 过期时间
        expires_time = 86400 * 2 if in_device == 'web' else 86400 * 30

        sql = "SELECT * FROM information_user where name = '%s' " % (in_name)
        results = tools.mysql_short_get(sql)

        if len(results) == 0:
            return {'code': 1001, 'data': '', 'msg': '账号密码错误'}

        key = results[0][2]
        googlekey = results[0][5]
        level = results[0][4]

        if in_password != key:
            return {'code': 1001, 'data': '', 'msg': '账号密码错误'}
        else:
            if config['check_googlecode']:  # 若检查谷歌验证码
                if str(in_googlekey) != calGoogleCode(googlekey):
                    return {'code': 1001, 'data': '', 'msg': '谷歌验证码错误'}

            s = Serializer(secret_key, expires_in=expires_time)
            token = s.dumps({'id': in_name, 'level': level}).decode("ascii")

            return {'code': 1000, 'data': {'user': in_name, 'access': level, 'token': token}, 'msg': '登录成功'}

    result = fun_quant_login()

    if g.device == 'web':
        if result['msg'] == '账号密码错误':
            return respond({'code': 1008, 'data': {'msg': '账号密码错误'}, 'msg': ''})
        elif result['msg'] == '谷歌验证码错误':
            return respond({'code': 1008, 'data': {'msg': '谷歌验证码错误'}, 'msg': ''})
        elif result['msg'] == '登录成功':
            return respond({'code': 1000, 'data': {'user': result['data']['user'], 'access': [result['data']['access']], 'token': result['data']['token']}, 'msg': ''})
    elif g.device == 'app':
        return respond(result)
    else:
        return respond({'code': 1001, 'data': '', 'msg': '设备识别错误'})


# 1.2获取用户信息，根据token反解user,level
@app.route("/quant/get_info", methods=['POST'])
def quant_get_info():
    data_in = g.data_in

    in_token = data_in['token']

    def fun_quant_get_info():

        results = verify_token(in_token)
        if results == 'token过期':
            return {'code': 1001, 'data': '', 'msg': 'Token过期,请重新登录!'}

        user = verify_token(in_token)['id']
        level = verify_token(in_token)['level']

        return {'code': 1000, 'data': {'user': user, 'access': level, 'token': in_token}, 'msg': '登录成功'}

    result = fun_quant_get_info()

    if g.device == 'web':
        if result['msg'] == 'Token过期,请重新登录!':
            return respond({'code': 1003, 'data': {'msg': 'token过期'}, 'msg': ''})
        elif result['msg'] == '登录成功':
            return respond({'code': 1000, 'data': {'user': result['data']['user'], 'access': [result['data']['access']]}, 'msg': ''})
    elif g.device == 'app':
        return respond(result)
    else:
        return respond({'code': 1001, 'data': '', 'msg': '设备识别错误'})


# 2.1.0.1获取价格
@app.route("/quant/trade/get_list_price_pro", methods=['POST'])
def quant_trade_get_list_price_pro():
    data_in = g.data_in

    dict_price = tools.get_price_dict()

    temp_dict = {}
    for key_dict_price in dict_price:
        contract = key_dict_price
        price_now = tools.get_price(dict_price=dict_price, contract_code=contract,price_type='市价')
        price_index = tools.get_price(dict_price=dict_price, contract_code=contract, price_type='指数价')
        price_mark = tools.get_price(dict_price=dict_price, contract_code=contract, price_type='标记价')

        temp_dict[contract] = {}

        temp_dict[contract]['price_now'] = price_now
        temp_dict[contract]['price_index'] = int(price_index * 100) / 100
        temp_dict[contract]['price_of_stop_profit_and_stop_loss'] = 'price_new'
        temp_dict[contract]['price_mark'] = int(price_mark * 100) / 100

    temp_data_out = temp_dict

    return respond({'code': 1000, 'data': temp_data_out, 'msg': '价格刷新'})


# 2.1.1获取用户列表
@app.route("/quant/trade/get_list_client", methods=['POST'])
def quant_trade_get_list_client():
    data_in = g.data_in

    try:
        if g.level == 'admin':
            sql = "SELECT name,contract FROM information_client"
            results = tools.mysql_short_get(sql)
        elif g.level == 'trader':
            sql = "SELECT name,contract FROM information_client where trader ='%s' " % (g.user)
            results = tools.mysql_short_get(sql)
        else:
            results = []

        temp_list = []
        for result in results:
            if result[0] not in temp_list:
                temp_list.append(result[0])

        data2 = {'clients': [], 'client_contract': {}}
        for result in results:
            name = result[0]
            contract = result[1]

            if name not in data2['clients']:
                data2['clients'].append(name)

            if name not in data2['client_contract']:
                data2['client_contract'][name] = []
            data2['client_contract'][name].append(contract)

        data_out = {'code': 1000, 'data': {'list_client': temp_list,'data2':data2}}
    except:
        data_out = {'code': 1001, 'data': {'msg': '业务异常'}}
    return respond(data_out)


# 2.1.2获取可以交易合约列表
@app.route("/quant/trade/get_list_contract", methods=['POST'])
def quant_trade_get_list_contract():
    data_in = g.data_in

    try:
        client_name = data_in['client']

        sql = "SELECT contract FROM information_client where  name = '%s' and open_or_close='开启' " % (client_name)
        results = tools.mysql_short_get(sql)

        temp_list = []
        for result in results:
            temp_list.append(result[0])

        temp_list.sort()

        data_out = {'code': 1000, 'data': {'list_contract': temp_list}}
        return respond(data_out)
    except:
        data_out = {'code': 1001, 'data': {'msg': '业务异常'}}
        return respond(data_out)


# 2.1.3获取某用户，某合约基本信息
@app.route("/quant/trade/get_client_info", methods=['POST'])
def quant_trade_get_client_info():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']

    price_dict = tools.get_price_dict()
    price_index = tools.get_price(price_dict, contract_code=in_contract, price_type='指数价')
    price_now = tools.get_price(price_dict, contract_code=in_contract, price_type='市价')

    sql = "SELECT swap_margin_balance,swap_buy_volume,swap_sell_volume,swap_profit_unreal,count_of_orders_active,下终止,上终止,止损时间,多单最大仓位,空单最大仓位,当前强平点,多单强平点,空单强平点,end_up_type,end_down_type,end_time_type,end_up_price_type,end_down_price_type,lowest_net_worth,buy_straight_up,buy_straight_down,buy_cycle_up,buy_cycle_down,sell_straight_up,sell_straight_down,sell_cycle_up,sell_cycle_down,account_straight_up,account_straight_down,account_cycle_up,account_cycle_down,profit_loss_cal_status_unrun,swap_buy_lever_rate,count_of_orders_exchange,highest_net_worth,tick_handle_time,eta_end_all,tick_handle_delay,adl FROM information_client where name = '%s' and contract = '%s' " % (in_client, in_contract)
    results = tools.mysql_short_get(sql)

    temp_dict = {}
    temp_dict['basic'] = {}
    temp_dict['risk'] = {}
    temp_dict['basic']['static'] = tools.get_display_number(number=results[0][0], contract=in_contract)
    temp_dict['basic']['buy_volume'] = str(int(float(results[0][1])))
    temp_dict['basic']['sell_volume'] = str(int(float(results[0][2])))
    temp_dict['basic']['profit_unreal'] = str(round(float(results[0][3]), 4))
    temp_dict['basic']['count_of_active_orders'] = '本地:' + results[0][4] + ',' + '交易所:' + results[0][33]
    temp_dict['basic']['cny'] = str(round(float(results[0][0]) *float(price_index),1)) if 'USDT' not in in_contract else str(round(float(results[0][0]) /price_now *price_index,1))
    temp_dict['basic']['lever_rate'] = results[0][32] + 'X'
    temp_dict['basic']['lowest_net_worth'] = tools.get_display_number(number=results[0][18], contract=in_contract)
    temp_dict['basic']['highest_net_worth'] = tools.get_display_number(number=results[0][34], contract=in_contract)
    temp_dict['basic']['contract_unit'] = ' USDT' if 'USDT' in in_contract else ' BTC'
    temp_dict['basic']['legal_currency_unit'] = '$'
    temp_dict['risk']['end_down'] = results[0][5]
    temp_dict['risk']['end_up'] = results[0][6]
    temp_dict['risk']['end_time'] = results[0][7]
    if temp_dict['risk']['end_time'] != 'None':
        temp_dict['risk']['end_time'] = str(int(float(results[0][7]) * 1000))
    temp_dict['risk']['buy_volume_max'] = results[0][8]
    temp_dict['risk']['sell_volume_max'] = results[0][9]
    temp_dict['risk']['liquidation_price'] = str(round(float(results[0][10]), 2)) if results[0][10] != '--' else '--'
    temp_dict['risk']['liquidation_buy'] = results[0][11]
    temp_dict['risk']['liquidation_sell'] = results[0][12]
    temp_dict['risk']['end_up_type'] = results[0][13]
    temp_dict['risk']['end_down_type'] = results[0][14]
    temp_dict['risk']['end_time_type'] = results[0][15]
    temp_dict['risk']['end_up_price_type'] = results[0][16]
    temp_dict['risk']['end_down_price_type'] = results[0][17]
    temp_dict['risk']['adl'] = results[0][38]

    # 开始构建盈亏数据
    buy_straight_up = tools.get_display_number(number=results[0][19], contract=in_contract)
    buy_straight_down = tools.get_display_number(number=results[0][20], contract=in_contract)
    buy_cycle_up = tools.get_display_number(number=results[0][21], contract=in_contract)
    buy_cycle_down = tools.get_display_number(number=results[0][22], contract=in_contract)
    sell_straight_up = tools.get_display_number(number=results[0][23], contract=in_contract)
    sell_straight_down = tools.get_display_number(number=results[0][24], contract=in_contract)
    sell_cycle_up = tools.get_display_number(number=results[0][25], contract=in_contract)
    sell_cycle_down = tools.get_display_number(number=results[0][26], contract=in_contract)
    account_straight_up = tools.get_display_number(number=results[0][27], contract=in_contract)
    account_straight_down = tools.get_display_number(number=results[0][28], contract=in_contract)
    account_cycle_up = tools.get_display_number(number=results[0][29], contract=in_contract)
    account_cycle_down = tools.get_display_number(number=results[0][30], contract=in_contract)
    profit_loss_cal_status_unrun = results[0][31]

    try:
        temp_dict['max_profit_and_loss_data'] = [{'name': '空单', 'c1': sell_straight_up, 'c1_color': False, 'c2': sell_cycle_up, 'c2_color': False, 'c3': sell_straight_down, 'c3_color': False, 'c4': sell_cycle_down, 'c4_color': False},
                                                 {'name': '多单', 'c1': buy_straight_up, 'c1_color': False, 'c2': buy_cycle_up, 'c2_color': False, 'c3': buy_straight_down, 'c3_color': False, 'c4': buy_cycle_down, 'c4_color': False},
                                                 {'name': '账户', 'c1': account_straight_up, 'c1_color': False if float(results[0][0]) + float(results[0][27]) > 0 else True, 'c2': account_cycle_up, 'c2_color': False if float(results[0][0]) + float(results[0][29]) > 0 else True, 'c3': account_straight_down, 'c3_color': False if float(results[0][0]) + float(results[0][28]) > 0 else True, 'c4': account_cycle_down, 'c4_color': False if float(results[0][0]) + float(results[0][30]) > 0 else True}]
    except:
        temp_dict['max_profit_and_loss_data'] = [
            {'name': '空单', 'c1': sell_straight_up, 'c1_color': True, 'c2': sell_cycle_up, 'c2_color': True, 'c3': sell_straight_down, 'c3_color': True, 'c4': sell_cycle_down, 'c4_color': True},
            {'name': '多单', 'c1': buy_straight_up, 'c1_color': True, 'c2': buy_cycle_up, 'c2_color': True, 'c3': buy_straight_down, 'c3_color': True, 'c4': buy_cycle_down, 'c4_color': True},
            {'name': '账户', 'c1': account_straight_up, 'c1_color': True, 'c2': account_cycle_up, 'c2_color': True, 'c3': account_straight_down, 'c3_color': True, 'c4': account_cycle_down, 'c4_color': True}
        ]

    # 盈亏计算是否包含未启动滑块
    def str_to_bool(str):
        if str == 'True':
            return True
        else:
            return False

    temp_dict['profit_loss_cal_status_unrun'] = str_to_bool(profit_loss_cal_status_unrun)
    temp_dict['profiling'] = {'tick_handle_time': f'Tick处理时间：{round(float(results[0][35])*1000,1)} ms', 'eta_end_all': f'全部平仓预计时间：{results[0][36]} s', 'tick_handle_delay':f'Tick处理延迟：{round(float(results[0][37])*1000,1)} ms'}

    return respond({'code': 1000, 'data': temp_dict, 'msg': '基本信息刷新'})


# 2.2.1获取某用户，某合约，某策略的基础参数 or 批量参数
@app.route("/quant/trade/get_parameter", methods=['POST'])
def quant_trade_get_parameter():

    data_in = g.data_in
    # 此处开始执行业务逻辑
    in_client = data_in['client']
    in_contract = data_in['contract']
    in_strategy = data_in['strategy']
    in_basic_or_batch = data_in['basic_or_batch']

    if in_basic_or_batch == 'basic':
        sql = "SELECT strategy_id,preset_name,client_name,contract,strategy,stop_loss,stop_loss_type,stop_profit,stop_profit_type,stop_amount_cycle,stop_time,stop_time_type,stop_time_time_or_len,stop_time_len,stop_loss_price_type,stop_profit_price_type FROM strategy_parameter_cycle_preset WHERE client_name='%s' and contract='%s' and strategy='%s' and basic_or_batch='%s' " % (in_client, in_contract, in_strategy, in_basic_or_batch)
        results = tools.mysql_short_get(sql)

        if len(results) != 0:
            temp_list = []
            for result in results:
                temp_dict = {}
                temp_dict['strategy_id'] = result[0]
                temp_dict['preset_name'] = result[1]
                temp_dict['client_name'] = result[2]
                temp_dict['contract'] = result[3]
                temp_dict['strategy'] = result[4]
                temp_dict['stop_loss'] = '' if result[5] == 'None' else result[5]
                temp_dict['stop_loss_type'] = result[6]
                temp_dict['stop_loss_price_type'] = result[14]
                temp_dict['stop_profit'] = '' if result[7] == 'None' else result[7]
                temp_dict['stop_profit_type'] = result[8]
                temp_dict['stop_profit_price_type'] = result[15]
                temp_dict['stop_amount_cycle'] = result[9]
                temp_dict['stop_time'] = int(float(result[10]) * 1000) if result[10] != 'None' else result[10]
                temp_dict['stop_time_type'] = result[11]
                temp_dict['stop_time_time_or_len'] = result[12]
                temp_dict['stop_time_len'] = result[13]

                temp_list.append(temp_dict)

            data_out = {'code': 1000, 'data': temp_list, 'msg': '刷新成功'}
        else:
            data_out = {'code': 1000, 'data': [], 'msg': '没有数据'}
    elif in_basic_or_batch == 'batch':
        sql = "SELECT strategy_id,preset_name,client_name,contract,strategy,batch FROM strategy_parameter_cycle_preset WHERE client_name='%s' and contract='%s' and strategy='%s' and basic_or_batch='%s' " % (in_client, in_contract, in_strategy, in_basic_or_batch)
        results = tools.mysql_short_get(sql)

        if len(results) != 0:
            temp_list = []
            for result in results:
                temp_dict = {}
                temp_dict['strategy_id'] = result[0]
                temp_dict['preset_name'] = result[1]
                temp_dict['client_name'] = result[2]
                temp_dict['contract'] = result[3]
                temp_dict['strategy'] = result[4]
                temp_temp_dict = eval(result[5])
                temp_dict['batch_kind'] = temp_temp_dict['批量类型']
                temp_dict['delt_open'] = temp_temp_dict['开仓价格间隔']
                temp_dict['delt_close'] = temp_temp_dict['平仓价格间隔']
                temp_dict['delt_volume'] = temp_temp_dict['仓位间隔']
                temp_dict['amount'] = temp_temp_dict['总单数']

                temp_list.append(temp_dict)

            data_out = {'code': 1000, 'data': temp_list, 'msg': '刷新成功'}
        else:
            data_out = {'code': 1000, 'data': [], 'msg': '没有数据'}
    else:
        data_out = {'code': 1000, 'data': [], 'msg': '没有数据'}

    return respond(data_out)


def dada_in_check_parameter(data_in):

    temp_preset_name = data_in['preset_name']
    temp_client_name = data_in['client_name']
    temp_contract = data_in['contract']
    temp_strategy = data_in['strategy']
    temp_basic_or_batch = data_in['basic_or_batch']

    type_check, msg, data_in['preset_name'] = typecheck.is_str(temp_preset_name)
    if not type_check:
        return False, f'参数名称||{msg}', ''

    if temp_basic_or_batch == 'basic':
        # temp_stop_time_time_or_len 可选参数，None,time,len

        data_in['stop_loss'] = 'None' if len(data_in['stop_loss']) == 0 else data_in['stop_loss']
        temp_stop_loss_type = data_in['stop_loss_type']
        temp_stop_loss_price_type = data_in['stop_loss_price_type']
        data_in['stop_profit'] = 'None' if len(data_in['stop_profit']) == 0 else data_in['stop_profit']
        temp_stop_profit_type = data_in['stop_profit_type']
        temp_stop_profit_price_type = data_in['stop_profit_price_type']
        temp_stop_amount_cycle = data_in['stop_amount_cycle']
        temp_stop_time_type = data_in['stop_time_type']
        temp_stop_time_time_or_len = data_in['stop_time_time_or_len']
        if temp_stop_time_time_or_len == 'None':
            temp_stop_time_time_or_len = 'None'
            temp_stop_time = 'None'
            temp_stop_time_len = 'None'
        else:
            temp_stop_time = data_in['stop_time']
            temp_stop_time_len = data_in['stop_time_len']
        temp_basic_or_batch = data_in['basic_or_batch']

        if temp_stop_amount_cycle == '':
            return False, f'循环次数||循环次数不可为空', ''

        type_check, msg, data_in['stop_amount_cycle'] = typecheck.is_posint(temp_stop_amount_cycle)
        if not type_check:
            return False, f'循环次数||{msg}', ''

        if data_in['stop_loss'] != 'None':
            type_check, msg, data_in['stop_loss'] = typecheck.is_posfloat(data_in['stop_loss'], tools.get_contract_precision(temp_contract))
            if not type_check:
                return False, f'止损价格||{msg}', ''

        if data_in['stop_profit'] != 'None':
            type_check, msg, data_in['stop_profit'] = typecheck.is_posfloat(data_in['stop_profit'], tools.get_contract_precision(temp_contract))
            if not type_check:
                return False, f'止盈价格||{msg}', ''

        if temp_stop_time_time_or_len == 'time':
            if temp_stop_time != 'None':
                type_check, msg, data_in['stop_time'] = typecheck.is_posint(temp_stop_time, border=False)
                if not type_check:
                    return False, f'终止时间||格式不正确', ''

                temp_stop_time = int(temp_stop_time) / 1000
                if temp_stop_time < time.time():
                    return False, '终止时间需大于当前时间', ''

        if temp_stop_time_time_or_len == 'len':
            if temp_stop_time_len != 'None':
                type_check, msg, data_in['stop_time_len'] = typecheck.is_posfloat(temp_stop_time_len)
                if not type_check:
                    return False, f'运行时长||{msg}', ''

    # 若新建的为批量参数
    elif temp_basic_or_batch == 'batch':

        temp_batch = {}
        temp_batch['批量类型'] = data_in['batch_kind']
        temp_batch['开仓价格间隔'] = data_in['delt_open'].replace('－', '-')
        temp_batch['平仓价格间隔'] = data_in['delt_close'].replace('－', '-')
        temp_batch['仓位间隔'] = data_in['delt_volume'].replace('－', '-')
        temp_batch['总单数'] = data_in['amount']

        type_check, msg, data_in['delt_open'] = typecheck.is_float(temp_batch['开仓价格间隔'], tools.get_contract_precision(temp_contract))
        if not type_check:
            return False, f'开仓价格间隔||{msg}', ''

        type_check, msg, data_in['delt_close'] = typecheck.is_float(temp_batch['平仓价格间隔'], tools.get_contract_precision(temp_contract))
        if not type_check:
            return False, f'平仓价格间隔||{msg}', ''

        type_check, msg, data_in['delt_volume'] = typecheck.is_int(temp_batch['仓位间隔'])
        if not type_check:
            return False, f'仓位间隔||{msg}', ''

        type_check, msg, data_in['amount'] = typecheck.is_posint(temp_batch['总单数'])
        if not type_check:
            return False, f'总单数||{msg}', ''

    msg = ''
    return True, msg, data_in


# 2.2.2新建某用户，某合约，某策略的基础参数 or 批量参数
@app.route("/quant/trade/insert_parameter", methods=['POST'])
def quant_trade_insert_parameter():
    data_in_ori = g.data_in
    data_in_refresh = copy.deepcopy(data_in_ori)

    # 输入值检查
    type_check, msg, data_in_refresh = dada_in_check_parameter(data_in_refresh)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'{msg}'})

    temp_preset_name = data_in_ori['preset_name']
    temp_client_name = data_in_ori['client_name']
    temp_contract = data_in_ori['contract']
    temp_strategy = data_in_ori['strategy']
    temp_basic_or_batch = data_in_ori['basic_or_batch']

    # 若新建的为基础参数
    if temp_basic_or_batch == 'basic':
        # temp_stop_time_time_or_len 可选参数，None,time,len

        temp_stop_loss = 'None' if len(data_in_ori['stop_loss']) == 0 else data_in_ori['stop_loss']
        temp_stop_loss_type = data_in_ori['stop_loss_type']
        temp_stop_loss_price_type = data_in_ori['stop_loss_price_type']
        temp_stop_profit = 'None' if len(data_in_ori['stop_profit']) == 0 else data_in_ori['stop_profit']
        temp_stop_profit_type = data_in_ori['stop_profit_type']
        temp_stop_profit_price_type = data_in_ori['stop_profit_price_type']
        temp_stop_amount_cycle = data_in_ori['stop_amount_cycle']
        temp_stop_time_type = data_in_ori['stop_time_type']
        temp_stop_time_time_or_len = data_in_ori['stop_time_time_or_len']
        if temp_stop_time_time_or_len == 'None':
            temp_stop_time_time_or_len = 'None'
            temp_stop_time = 'None'
            temp_stop_time_len = 'None'
        else:
            temp_stop_time = data_in_ori['stop_time']
            temp_stop_time_len = data_in_ori['stop_time_len']
        temp_basic_or_batch = data_in_ori['basic_or_batch']

        if temp_stop_time_time_or_len == 'time':
            if temp_stop_time != 'None':
                temp_stop_time = int(temp_stop_time) / 1000

        sql = "INSERT INTO strategy_parameter_cycle_preset (preset_name,client_name,contract,strategy,stop_loss,stop_loss_type,stop_loss_price_type,stop_profit,stop_profit_type,stop_profit_price_type,stop_amount_cycle ,stop_time_time_or_len,stop_time,stop_time_len,basic_or_batch,stop_time_type) " \
              "VALUES('%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s')" % \
              (temp_preset_name, temp_client_name, temp_contract, temp_strategy, temp_stop_loss, temp_stop_loss_type, temp_stop_loss_price_type, temp_stop_profit, temp_stop_profit_type, temp_stop_profit_price_type, temp_stop_amount_cycle, temp_stop_time_time_or_len, temp_stop_time, temp_stop_time_len, temp_basic_or_batch, temp_stop_time_type)
        tools.mysql_short_commit(sql)

    # 若新建的为批量参数
    elif temp_basic_or_batch == 'batch':

        temp_batch = {}
        temp_batch['批量类型'] = data_in_ori['batch_kind']
        temp_batch['开仓价格间隔'] = data_in_ori['delt_open']
        temp_batch['平仓价格间隔'] = data_in_ori['delt_close']
        temp_batch['仓位间隔'] = data_in_ori['delt_volume']
        temp_batch['总单数'] = data_in_ori['amount']

        temp_batch = str(temp_batch).replace("\'", "\'\'")
        sql = "INSERT INTO strategy_parameter_cycle_preset (preset_name,client_name,contract,strategy,batch,basic_or_batch) " \
              "VALUES('%s','%s','%s','%s','%s','%s')" % \
              (temp_preset_name, temp_client_name, temp_contract, temp_strategy, temp_batch, temp_basic_or_batch)
        tools.mysql_short_commit(sql)

    return respond({'code': 1000, 'data': '', 'msg': '保存成功'})


# 2.2.3修改某用户，某合约，某策略的基础参数 or 批量参数
@app.route("/quant/trade/update_parameter", methods=['POST'])
def quant_trade_update_parameter():
    data_in_ori = g.data_in
    data_in_refresh = copy.deepcopy(data_in_ori)

    # 输入值检查
    type_check, msg, data_in_refresh = dada_in_check_parameter(data_in_refresh)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'{msg}'})

    temp_strategy_id = data_in_ori['strategy_id']
    temp_preset_name = data_in_ori['preset_name']
    temp_client_name = data_in_ori['client_name']
    temp_contract = data_in_ori['contract']
    temp_strategy = data_in_ori['strategy']
    temp_basic_or_batch = data_in_ori['basic_or_batch']

    # 若修改的为基础参数
    if temp_basic_or_batch == 'basic':

        temp_stop_loss = 'None' if len(data_in_ori['stop_loss']) == 0 else data_in_ori['stop_loss']
        temp_stop_loss_type = data_in_ori['stop_loss_type']
        temp_stop_loss_price_type = data_in_ori['stop_loss_price_type']
        temp_stop_profit = 'None' if len(data_in_ori['stop_profit']) == 0 else data_in_ori['stop_profit']
        temp_stop_profit_type = data_in_ori['stop_profit_type']
        temp_stop_profit_price_type = data_in_ori['stop_profit_price_type']
        temp_stop_amount_cycle = data_in_ori['stop_amount_cycle']
        temp_stop_time_time_or_len = data_in_ori['stop_time_time_or_len']
        temp_stop_time = data_in_ori['stop_time']
        temp_stop_time_len = data_in_ori['stop_time_len']
        temp_stop_time_type = data_in_ori['stop_time_type']

        if temp_stop_time_time_or_len == 'time':
            if temp_stop_time != 'None':
                temp_stop_time = int(temp_stop_time) / 1000

        sql = "UPDATE strategy_parameter_cycle_preset SET preset_name='%s',stop_loss='%s',stop_loss_type='%s',stop_loss_price_type='%s',stop_profit='%s',stop_profit_type='%s',stop_profit_price_type='%s',stop_amount_cycle='%s',stop_time_time_or_len='%s',stop_time='%s',stop_time_len='%s',stop_time_type='%s' WHERE strategy_id = '%s' " % (
            temp_preset_name, temp_stop_loss, temp_stop_loss_type, temp_stop_loss_price_type, temp_stop_profit, temp_stop_profit_type, temp_stop_profit_price_type, temp_stop_amount_cycle, temp_stop_time_time_or_len, temp_stop_time, temp_stop_time_len, temp_stop_time_type, temp_strategy_id)
        tools.mysql_short_commit(sql)

    # 若修改的为批量参数
    elif temp_basic_or_batch == 'batch':

        temp_batch = {}
        temp_batch['批量类型'] = data_in_ori['batch_kind']
        temp_batch['开仓价格间隔'] = data_in_ori['delt_open']
        temp_batch['平仓价格间隔'] = data_in_ori['delt_close']
        temp_batch['仓位间隔'] = data_in_ori['delt_volume']
        temp_batch['总单数'] = data_in_ori['amount']

        temp_batch = str(temp_batch).replace("\'", "\'\'")

        sql = "UPDATE strategy_parameter_cycle_preset SET preset_name='%s',batch='%s' WHERE strategy_id = '%s' " % (temp_preset_name, temp_batch, temp_strategy_id)
        tools.mysql_short_commit(sql)

    return respond({'code': 1000, 'data': '', 'msg': '编辑成功'})


# 2.2.4删除某用户，某合约，某策略的基础参数 or 批量参数
@app.route("/quant/trade/delete_parameter", methods=['POST'])
def quant_trade_delete_parameter():
    data_in = g.data_in

    in_basic_or_batch = data_in['basic_or_batch']
    in_strategy_id = data_in['strategy_id']

    sql = "DELETE FROM strategy_parameter_cycle_preset WHERE strategy_id = '%s' and basic_or_batch='%s' " % (in_strategy_id, in_basic_or_batch)
    tools.mysql_short_commit(sql)

    return respond({'code': 1000, 'data': '', 'msg': '删除成功'})


# 2.3.-1 获取某用户，某合约的所有策略（含未启动和启动）
@app.route("/quant/trade/get_list_strategy_pro", methods=['POST'])
def quant_trade_get_list_strategy_pro():

    data_in = g.data_in
    # 此处开始执行业务逻辑
    in_client = data_in['client']
    in_contract = data_in['contract']

    db = MySQLdb.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    sql = "SELECT strategy_id,strategy_type,open,close,direction,inposition,volume,points_translation,stop_loss,stop_loss_type,stop_profit,stop_profit_type,stop_amount_cycle,stop_time,stop_time_type,stop_time_time_or_len,stop_time_len,create_time,strategy_status,amount_cycle,group_id,stop_loss_price_type,stop_profit_price_type,points_translation_time,counts_of_points_translation,counts_of_points_translation_opposite,average_opening_price FROM strategy_parameter_cycle_run where client_name='%s' and contract_type='%s' ORDER BY (OPEN+0) DESC " % (
        in_client, in_contract)
    cursor.execute(sql)  # 执行SQL语句
    results = cursor.fetchall()  # 获取所有记录列表
    db.close()

    temp_list_unrun = []
    temp_list_run = []
    temp_list_group_id_run = []
    temp_list_group_id_unrun = []
    temp_data_group_id_run = {}
    temp_data_group_id_unrun = {}
    for result in results:
        temp_dict = {}
        temp_dict['strategy_id'] = result[0]
        temp_dict['strategy_type'] = result[1]
        temp_dict['open'] = result[2]
        temp_dict['close'] = str(result[3])
        temp_dict['direction'] = result[4]
        if len(str(result[5])) != 0:
            temp_dict['inposition'] = int(float(result[5]))

        if len(result[6]) != 0:
            temp_dict['volume'] = str(int(float(result[6])))
        temp_dict['display_inposition_volume'] = str(int(float(result[5]))) + '/' + str(int(float(result[6])))
        temp_dict['points_translation'] = result[7]
        temp_dict['stop_loss'] = result[8]
        temp_dict['stop_loss_type'] = result[9]
        temp_dict['stop_profit'] = result[10]
        temp_dict['stop_profit_type'] = result[11]
        temp_dict['stop_amount_cycle'] = result[12]
        temp_dict['stop_time'] = result[13]
        if temp_dict['stop_time'] != 'None':
            if len(result[13]) != 0:
                temp_dict['stop_time'] = str(float(result[13]) * 1000)
        temp_dict['stop_time_type'] = result[14]
        temp_dict['stop_time_time_or_len'] = result[15]
        temp_dict['stop_time_len'] = result[16]
        #修正渲染
        if temp_dict['stop_time_time_or_len'] == 'None':
            temp_dict['stop_time'] = 'None'
        elif temp_dict['stop_time_time_or_len'] == 'time':
            temp_dict['stop_time_len'] = 'None'
        elif temp_dict['stop_time_time_or_len'] == 'len':
            temp_dict['stop_time'] = 'None'

        if len(result[17]) != 0:
            temp_dict['create_time'] = str(
                int(float(result[17]) * 1000))
        temp_dict['strategy_status'] = result[18]
        if temp_dict['strategy_status'] == 'normal':
            temp_dict['strategy_status'] = '运行中'
        temp_dict['amount_cycle'] = str(int(float(result[19])))
        temp_dict['display_amount_cycle_stop_amount_cycle'] = str(
            int(float(result[19]))) + '/' + str(int(float(result[12])))
        temp_dict['group_id'] = result[20]
        temp_dict['stop_loss_price_type'] = result[21]
        temp_dict['stop_profit_price_type'] = result[22]
        try:
            temp_dict['points_translation_time'] = str(
                int(float(result[23]) * 1000))
        except BaseException:
            temp_dict['points_translation_time'] = ''

        temp_dict['points_translation_times'] = int(float(result[24]))
        temp_dict['points_translation_times_opp'] = int(float(result[25]))
        temp_dict['average_opening_price'] = result[26]

        if temp_dict['inposition'] == 0:
            temp_dict['group_id_pro'] = str(result[20]) + '-未持仓'
            temp_dict['group_id_pro_2'] = str(result[4]) + '单-未持仓'
        else:
            temp_dict['group_id_pro'] = str(result[20]) + '-已持仓'
            temp_dict['group_id_pro_2'] = str(result[4]) + '单-已持仓'

        if temp_dict['strategy_status'] == '未启动':
            temp_list_unrun.append(temp_dict)
        else:
            temp_list_run.append(temp_dict)

        if result[18] == '未启动':
            if temp_dict['group_id'] not in temp_list_group_id_unrun:
                temp_list_group_id_unrun.append(temp_dict['group_id'])
                temp_temp_data_group_id_unrun_1 = str(
                    result[20]) + '-未持仓'
                temp_temp_data_group_id_unrun_2 = str(
                    result[20]) + '-已持仓'
                temp_data_group_id_unrun[temp_temp_data_group_id_unrun_2] = 0
                temp_data_group_id_unrun[temp_temp_data_group_id_unrun_1] = 0
        else:
            if temp_dict['group_id'] not in temp_list_group_id_run:
                temp_list_group_id_run.append(temp_dict['group_id'])
                temp_temp_data_group_id_run_1 = str(
                    result[20]) + '-未持仓'
                temp_temp_data_group_id_run_2 = str(
                    result[20]) + '-已持仓'
                temp_data_group_id_run[temp_temp_data_group_id_run_2] = 0
                temp_data_group_id_run[temp_temp_data_group_id_run_1] = 0

        if result[18] == '未启动':
            temp_data_group_id_unrun[temp_dict['group_id_pro']
                                     ] = temp_data_group_id_unrun[temp_dict['group_id_pro']] + 1
        else:
            temp_data_group_id_run[temp_dict['group_id_pro']
                                   ] = temp_data_group_id_run[temp_dict['group_id_pro']] + 1

    # 整理data_group_id_run、data_group_id_unrun 格式
    data_group_id_run = []
    data_group_id_unrun = []
    for temp_temp_data_group_id_run in temp_data_group_id_run:
        temp_dict = {}
        temp_dict['group'] = temp_temp_data_group_id_run
        # 此处selectCount未按照下划线命名风格命名，非错误
        temp_dict['selectCount'] = 0
        temp_dict['count'] = temp_data_group_id_run[temp_temp_data_group_id_run]
        data_group_id_run.append(temp_dict)
    for temp_temp_data_group_id_unrun in temp_data_group_id_unrun:
        temp_dict = {}
        temp_dict['group'] = temp_temp_data_group_id_unrun
        # 此处selectCount未按照下划线命名风格命名，非错误
        temp_dict['selectCount'] = 0
        temp_dict['count'] = temp_data_group_id_unrun[temp_temp_data_group_id_unrun]
        data_group_id_unrun.append(temp_dict)

    data_group_id_run = sorted(data_group_id_run, key=lambda group_id_run: group_id_run['group'])
    data_group_id_unrun = sorted(data_group_id_unrun, key=lambda group_id_unrun: group_id_unrun['group'])
    temp_list_group_id_run = sorted(temp_list_group_id_run)
    temp_list_group_id_unrun = sorted(temp_list_group_id_unrun)

    data_out = {
        'code': 1000,
        'strategy_list_unrun': temp_list_unrun,
        'strategy_list_run': temp_list_run,
        'data_group_id_run': data_group_id_run,
        'data_group_id_unrun': data_group_id_unrun,
        'list_group_id_run': temp_list_group_id_run,
        'list_group_id_unrun': temp_list_group_id_unrun,
        'next_request_delay': max(1000, len(temp_list_run)+len(temp_list_unrun)),
        'msg': '数据刷新'}
    return respond(data_out)


# 2.3.1 获取某用户，某合约最新强平点
@app.route("/quant/trade/get_latest_liquidation", methods=['POST'])
def quant_trade_get_latest_liquidation():
    data_in = g.data_in

    # 待传入数据示例
    # data_in = {'client':'张玉昆','contract':'BTC-USD','strategy':'循环策略','open':'9000','close':'10000','volume':'1','basic_id':'157','batch_id':'158'}

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_strategy = '循环策略'
    in_open = data_in['open']
    in_close = data_in['close']
    in_volume = data_in['volume']
    in_batch_id = data_in['batch_id']

    # 开始计算强平
    def cal_liquidation(client_name, contract, data_in):
        try:
            # 请求样例
            # strategyList = [
            #     {'id': '1', 'direction': '多', 'open': '53700', 'close': '54100', 'volume': '400', 'orderId': '1243143'},
            #     {'id': '2', 'direction': '多', 'open': '53600', 'close': '54000', 'volume': '100', 'orderId': ''},
            #     {'id': '3', 'direction': '多', 'open': '53500', 'close': '53900', 'volume': '100', 'orderId': ''},
            #     {'id': '4', 'direction': '多', 'open': '53400', 'close': '53800', 'volume': '100', 'orderId': ''},
            #     {'id': '5', 'direction': '多', 'open': '53300', 'close': '53700', 'volume': '100', 'orderId': ''},
            #     {'id': '6', 'direction': '多', 'open': '53200', 'close': '53600', 'volume': '100', 'orderId': ''},
            #     {'id': '100', 'direction': '空', 'open': '54200', 'close': '53600', 'volume': '500', 'orderId': '433636'},
            #     {'id': '100', 'direction': '空', 'open': '54300', 'close': '53700', 'volume': '200', 'orderId': ''},
            #     {'id': '100', 'direction': '空', 'open': '54400', 'close': '53800', 'volume': '200', 'orderId': ''},
            #     {'id': '100', 'direction': '空', 'open': '54500', 'close': '53900', 'volume': '100', 'orderId': ''},
            #     {'id': '100', 'direction': '空', 'open': '54600', 'close': '54000', 'volume': '100', 'orderId': ''}
            # ]
            # serviceChargeRate = '0.0002'  # 手续费率
            # parValue = '100'  # 面值
            # multiple = '125'  # 杠杆倍数
            # upPosition = '400'  # 多方持仓
            # upAveragePositionPrice = '53700'  # 多方持仓均价
            # downPosition = '500'  # 空方持仓
            # downAveragePositionPrice = '54200'  # 空方持仓均价
            # staticBalance = '0.1'  # 静态权益
            # shortNumber = '5'  # 空方策略数
            # buyNumber = '6'  # 多方策略数

            # lowest_price = 0.1 ** tools.get_contract_precision(contract)
            # highest_price = 1000000

            # 数据库连接
            db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)

            # 查询开仓手续费率 maker
            sql = "SELECT maker_fee FROM information_client where name = '%s' and contract = '%s' " % (client_name, contract)
            open_rate = float(tools.mysql_fetchall(db,sql)[0][0])
            serviceChargeRate = open_rate

            # 查询平仓手续费率 taker
            sql = "SELECT taker_fee FROM information_client where name = '%s' and contract = '%s' " % (client_name, contract)
            close_rate = float(tools.mysql_fetchall(db,sql)[0][0])
            # 平仓手续费
            serviceChargeRateTaker = close_rate

            # 面值
            # parValue = config['exchange'][config['server_exchange']]['contract'][contract]['parvalue']

            if 'SWAP' in contract:
                config_contract = config['exchange'][config['server_exchange']][config['real_trading']]['contracts'][contract]
            else:
                config_contract = config['exchange'][config['server_exchange']][config['real_trading']]['contracts'][f"{contract.split('-')[0]}-{contract.split('-')[1]}-FUTURES"]

            parvalue = config_contract['parvalue']

            sql = "SELECT swap_buy_volume,swap_buy_cost_open,swap_sell_volume,swap_sell_cost_open,swap_margin_balance,swap_profit_unreal,swap_buy_lever_rate FROM information_client where name= '%s'  and contract = '%s' " % (
                client_name, contract)
            results1 = tools.mysql_fetchall(db, sql)

            # 多方向持仓数量
            upPosition = float(results1[0][0])
            # 多方向持仓均价
            upAveragePositionPrice = float(results1[0][1])
            # 空方向持仓数量
            downPosition = float(results1[0][2])
            # 空方向持仓均价
            downAveragePositionPrice = float(results1[0][3])
            # 静态权益=账户权益-未实现盈亏
            staticBalance = float(results1[0][4]) - float(results1[0][5])
            # 杠杆倍数
            multiple = float(results1[0][6])

            # 开始构件策略数据
            strategyList = []

            buy_max_volume = 0
            sell_max_volume = 0
            # {'id': '1', 'direction': '多', 'open': '53700', 'close': '54100', 'volume': '400', 'orderId': '1243143'},
            sql = "SELECT strategy_id,open,close,direction,volume,inposition,strategy_type FROM strategy_parameter_cycle_run where client_name='%s' and contract_type='%s' " % (
                client_name, contract)
            results = tools.mysql_fetchall(db, sql)
            for result in results:
                temp_dict = {}
                temp_dict['id'] = result[0]
                temp_dict['open'] = result[1]
                temp_dict['close'] = result[2]
                temp_dict['direction'] = result[3]
                temp_dict['volume'] = result[4]
                temp_dict['orderId'] = '' if float(result[5]) == 0 else '1'
                if temp_dict['direction'] == '多':
                    buy_max_volume = buy_max_volume + \
                        float(temp_dict['volume'])
                else:
                    sell_max_volume = sell_max_volume + \
                        float(temp_dict['volume'])

                strategyList.append(temp_dict)

            # 开始处理创建中数据
            in_client = data_in['client']
            in_contract = data_in['contract']
            in_strategy = '循环策略'
            in_open = data_in['open']
            in_close = data_in['close']
            in_volume = data_in['volume']
            in_batch_id = data_in['batch_id']

            contract = in_contract

            # 初始化临时参数列表
            if in_batch_id == 'None':

                temp_open = in_open
                temp_close = in_close
                temp_volume = in_volume

                temp_strategy = {}
                # {'id': '1', 'direction': '多', 'open': '53700', 'close': '54100', 'volume': '400', 'orderId': '1243143'}
                temp_strategy['id'] = 'creating'
                temp_strategy['direction'] = '多' if float(
                    temp_close) >= float(temp_open) else '空'
                temp_strategy['open'] = temp_open
                temp_strategy['close'] = temp_close
                temp_strategy['volume'] = temp_volume
                temp_strategy['orderId'] = ''
                strategyList.append(temp_strategy)

            elif in_batch_id != 'None':
                # 查批量参数
                sql = "SELECT batch FROM strategy_parameter_cycle_preset WHERE strategy_id='%s' " % (
                    in_batch_id)
                results2 = tools.mysql_fetchall(db, sql)

                temp_open = in_open
                temp_close = in_close
                temp_volume = in_volume
                temp_batch = eval(results2[0][0])

                if in_strategy == '循环策略':

                    batch_type = temp_batch['批量类型']

                    if batch_type == '等差':
                        batch_open_delt = temp_batch['开仓价格间隔']
                        batch_close_delt = temp_batch['平仓价格间隔']
                        batch_volume_delt = temp_batch['仓位间隔']
                        batch_amount_total = temp_batch['总单数']

                        # 先写入普通策略
                        temp_strategy = {}
                        # {'id': '1', 'direction': '多', 'open': '53700', 'close': '54100', 'volume': '400', 'orderId': '1243143'}
                        temp_strategy['id'] = 'creating'
                        temp_strategy['direction'] = '多' if float(
                            temp_close) >= float(temp_open) else '空'
                        temp_strategy['open'] = temp_open
                        temp_strategy['close'] = temp_close
                        temp_strategy['volume'] = temp_volume
                        temp_strategy['orderId'] = ''
                        strategyList.append(temp_strategy)

                        # 再处理批量策略
                        # int 去尾取整
                        batch_amount_total = int(float(batch_amount_total))
                        while batch_amount_total > 1:
                            temp_open = round(float(temp_open) + float(batch_open_delt),tools.get_contract_precision(contract))
                            temp_close = round(float(temp_close) + float(batch_close_delt),tools.get_contract_precision(contract))
                            temp_volume = int(float(temp_volume) + float(batch_volume_delt))
                            if temp_volume < 1:
                                temp_volume = 1
                            batch_amount_total -= 1

                            # 写入批量
                            temp_strategy = {}
                            # {'id': '1', 'direction': '多', 'open': '53700', 'close': '54100', 'volume': '400', 'orderId': '1243143'}
                            temp_strategy['id'] = 'creating'
                            temp_strategy['direction'] = '多' if float(
                                temp_close) >= float(temp_open) else '空'
                            temp_strategy['open'] = temp_open
                            temp_strategy['close'] = temp_close
                            temp_strategy['volume'] = temp_volume
                            temp_strategy['orderId'] = ''
                            strategyList.append(temp_strategy)

                    elif batch_type == '等比':
                        batch_open_delt = temp_batch['开仓价格间隔']
                        batch_close_delt = temp_batch['平仓价格间隔']
                        batch_volume_delt = temp_batch['仓位间隔']
                        batch_amount_total = temp_batch['总单数']

                        # 先写入普通策略
                        temp_strategy = {}
                        # {'id': '1', 'direction': '多', 'open': '53700', 'close': '54100', 'volume': '400', 'orderId': '1243143'}
                        temp_strategy['id'] = 'creating'
                        temp_strategy['direction'] = '多' if float(
                            temp_close) >= float(temp_open) else '空'
                        temp_strategy['open'] = temp_open
                        temp_strategy['close'] = temp_close
                        temp_strategy['volume'] = temp_volume
                        temp_strategy['orderId'] = ''
                        strategyList.append(temp_strategy)

                        # 再处理批量策略
                        # int 去尾取整
                        batch_amount_total = int(float(batch_amount_total))
                        while batch_amount_total > 1:
                            temp_open = round(float(temp_open) * (1 + float(batch_open_delt) / 100), 1)
                            temp_close = round(float(temp_close) * (1 + float(batch_close_delt) / 100), 1)
                            temp_volume = int(float(temp_volume) * (1 + float(batch_volume_delt) / 100))
                            if temp_volume < 1:
                                temp_volume = 1
                            batch_amount_total -= 1

                            # 写入批量
                            temp_strategy = {}
                            # {'id': '1', 'direction': '多', 'open': '53700', 'close': '54100', 'volume': '400', 'orderId': '1243143'}
                            temp_strategy['id'] = 'creating'
                            temp_strategy['direction'] = '多' if float(
                                temp_close) >= float(temp_open) else '空'
                            temp_strategy['open'] = temp_open
                            temp_strategy['close'] = temp_close
                            temp_strategy['volume'] = temp_volume
                            temp_strategy['orderId'] = ''
                            strategyList.append(temp_strategy)

            # 整理strategyList数据，计算
            buyNumber = 0
            shortNumber = 0

            for strategy in strategyList:
                if strategy['direction'] == '多':
                    buyNumber += 1
                else:
                    shortNumber += 1

            paramters = {
                'strategyList': strategyList,
                'serviceChargeRate': serviceChargeRate,
                'serviceChargeRateTaker': serviceChargeRateTaker,
                'parValue': parvalue,
                'multiple': multiple,
                'upPosition': upPosition,
                'upAveragePositionPrice': upAveragePositionPrice,
                'downPosition': downPosition,
                'downAveragePositionPrice': downAveragePositionPrice,
                'staticBalance': staticBalance,
                'shortNumber': shortNumber,
                'buyNumber': buyNumber,
                'contract': contract,
                'round_precision': tools.get_contract_precision(contract)
            }

            logger_content.info(f'请求计算强平,{paramters}')
            response = risk_cal.cal_liquidation(paramters)
            logger_content.info(f'计算结果,{response}')

            liquidation_buy = response['data']['liquidation_buy']
            liquidation_sell = response['data']['liquidation_sell']

            if liquidation_sell == 99999999:
                liquidation_sell = '无穷大'
            if liquidation_buy == 0:
                liquidation_buy = '0'

            db.close()

        except:
            print('traceback', traceback.format_exc())
            logger_content.info(traceback.format_exc())
            # print(traceback.format_exc())

        return liquidation_buy, liquidation_sell

    # 开始计算盈亏
    in_profit_loss_cal_status_run_and_unrun = str(data_in['profit_loss_cal_status_run_and_unrun'])

    if in_profit_loss_cal_status_run_and_unrun not in ['none', 'all', 'run', 'unrun']:
        data_out = {'code': 1001, 'data': '', 'msg': '参数不合法', 'msg': ''}
        return respond(data_out)
    if in_profit_loss_cal_status_run_and_unrun == 'none':
        in_cal_status_running = 'False'
        in_cal_status_unrun = 'False'
        in_cal_status_creatingcal_status_creating = 'True'
        in_cal_status_web = 'False'
    elif in_profit_loss_cal_status_run_and_unrun == 'all':
        in_cal_status_running = 'True'
        in_cal_status_unrun = 'True'
        in_cal_status_creatingcal_status_creating = 'True'
        in_cal_status_web = 'True'
    elif in_profit_loss_cal_status_run_and_unrun == 'run':
        in_cal_status_running = 'True'
        in_cal_status_unrun = 'False'
        in_cal_status_creatingcal_status_creating = 'True'
        in_cal_status_web = 'True'
    elif in_profit_loss_cal_status_run_and_unrun == 'unrun':
        in_cal_status_running = 'False'
        in_cal_status_unrun = 'True'
        in_cal_status_creatingcal_status_creating = 'True'
        in_cal_status_web = 'False'
    else:
        in_cal_status_running = 'True'
        in_cal_status_unrun = 'True'
        in_cal_status_creatingcal_status_creating = 'True'
        in_cal_status_web = 'True'

    def cal_profit_loss(client_name, contract, data_in, cal_status_running, cal_status_unrun, cal_status_creating, cal_status_web):
        try:
            # 计算目标值
            buy_straight_up = 0
            buy_straight_down = 0
            buy_cycle_up = 0
            buy_cycle_down = 0
            sell_straight_up = 0
            sell_straight_down = 0
            sell_cycle_up = 0
            sell_cycle_down = 0
            account_straight_up = 0
            account_straight_down = 0
            account_cycle_up = 0
            account_cycle_down = 0

            # 获取最新价格,保存为字典
            dict_price = tools.get_price_dict()
            # 调用示例: get_price(dict_price,contract = 'BTC-USD',price_type= '指数价')

            lowest_price = 0.1 ** tools.get_contract_precision(contract)
            highest_price = 1000000

            # 开始准备数据
            if 'SWAP' in contract:
                config_contract = config['exchange'][config['server_exchange']][config['real_trading']]['contracts'][contract]
            else:
                config_contract = config['exchange'][config['server_exchange']][config['real_trading']]['contracts'][f"{contract.split('-')[0]}-{contract.split('-')[1]}-FUTURES"]

            pur_value = config_contract['parvalue']

            price_new = tools.get_price(dict_price=dict_price, contract_code=contract, price_type='市价')

            # strategy={'open':open,'close':close,'stop_loss':stop_loss,'stop_profit':stop_profit,'volume':volume,'amount_cycle':amount_cycle,'stop_amount_cycle':stop_amount_cycle,'direction':direction,'trade_volume':trade_volume}
            # 止盈止损产生空缺时，多单止盈默认1000000.多单止损默认100，空单止盈默认100，空单止损默认1000000

            list_strategy = []
            if cal_status_running == 'True':
                sql = "SELECT open,close,stop_loss,stop_profit,volume,amount_cycle,stop_amount_cycle,direction,inposition FROM strategy_parameter_cycle_run where client_name='%s' and contract_type='%s' and strategy_status != '未启动' " % (client_name, contract)
                results = tools.mysql_short_get(sql)

                for result in results:
                    temp_dict_strategy = {}
                    temp_dict_strategy['open'] = result[0]
                    temp_dict_strategy['close'] = result[1]
                    temp_dict_strategy['stop_loss'] = result[2]
                    temp_dict_strategy['stop_profit'] = result[3]
                    temp_dict_strategy['volume'] = result[4]
                    temp_dict_strategy['amount_cycle'] = result[5]
                    temp_dict_strategy['stop_amount_cycle'] = result[6]
                    temp_dict_strategy['direction'] = result[7]
                    temp_dict_strategy['trade_volume'] = result[8]

                    list_strategy.append(temp_dict_strategy)

            # 计算未启动中策略
            if cal_status_unrun == 'True':
                sql = "SELECT open,close,stop_loss,stop_profit,volume,amount_cycle,stop_amount_cycle,direction,inposition FROM strategy_parameter_cycle_run where client_name='%s' and contract_type='%s' and strategy_status = '未启动' " % (client_name, contract)
                results = tools.mysql_short_get(sql)

                for result in results:
                    temp_dict_strategy = {}
                    temp_dict_strategy['open'] = result[0]
                    temp_dict_strategy['close'] = result[1]
                    temp_dict_strategy['stop_loss'] = result[2]
                    temp_dict_strategy['stop_profit'] = result[3]
                    temp_dict_strategy['volume'] = result[4]
                    temp_dict_strategy['amount_cycle'] = result[5]
                    temp_dict_strategy['stop_amount_cycle'] = result[6]
                    temp_dict_strategy['direction'] = result[7]
                    temp_dict_strategy['trade_volume'] = result[8]

                    list_strategy.append(temp_dict_strategy)
                # 计算创建中策略

            if cal_status_creating == 'True':
                # 获取数据
                def analysis_creating(data_in):
                    # 待传入数据示例
                    # data_in = {'client':'张玉昆','contract':'BTC-USD','strategy':'循环策略','open':'9000','close':'10000','volume':'1','basic_id':'157','batch_id':'158'}

                    # 此处开始执行业务逻辑
                    in_client = data_in['client']
                    in_contract = data_in['contract']
                    in_strategy = '循环策略'
                    in_open = data_in['open']
                    in_close = data_in['close']
                    in_volume = data_in['volume']
                    in_basic_id = data_in['basic_id']
                    in_batch_id = data_in['batch_id']

                    contract = in_contract

                    # 初始化策略参数列表
                    temp_list_strategy = []

                    sql = "SELECT stop_profit,stop_loss,stop_amount_cycle FROM strategy_parameter_cycle_preset WHERE strategy_id='%s' " % (in_basic_id)
                    results = tools.mysql_short_get(sql)

                    stop_profit = results[0][0]
                    stop_loss = results[0][1]
                    stop_amount_cycle = results[0][2]

                    def insert_temp_list_strategy():
                        temp_list_strategy.append(
                            {'open': temp_open, 'close': temp_close, 'stop_loss': stop_loss,
                             'stop_profit': stop_profit,
                             'volume': temp_volume, 'amount_cycle': 0, 'stop_amount_cycle': stop_amount_cycle,
                             'direction': direction, 'trade_volume': 0})

                    # 开始处理批量参数
                    if in_batch_id == 'None':

                        temp_open = in_open
                        temp_close = in_close
                        temp_volume = in_volume

                        # 分多空
                        if float(temp_open) < float(temp_close):
                            # 这是多单
                            direction = '多'
                        else:
                            # 这是空单
                            direction = '空'

                        insert_temp_list_strategy()
                    elif in_batch_id != 'None':
                        sql = "SELECT batch FROM strategy_parameter_cycle_preset WHERE strategy_id='%s' " % (in_batch_id)
                        results2 = tools.mysql_short_get(sql)

                        temp_open = in_open
                        temp_close = in_close
                        temp_volume = in_volume
                        temp_batch = eval(results2[0][0])

                        if in_strategy == '循环策略':

                            batch_type = temp_batch['批量类型']

                            if batch_type == '等差':
                                batch_open_delt = temp_batch['开仓价格间隔']
                                batch_close_delt = temp_batch['平仓价格间隔']
                                batch_volume_delt = temp_batch['仓位间隔']
                                batch_amount_total = temp_batch['总单数']

                                # 先写入普通策略
                                # 分多空
                                if float(temp_open) < float(temp_close):
                                    # 这是多单
                                    direction = '多'
                                else:
                                    # 这是空单
                                    direction = '空'

                                insert_temp_list_strategy()

                                # 再处理批量策略
                                # int 去尾取整
                                batch_amount_total = int(
                                    float(batch_amount_total))
                                while batch_amount_total > 1:
                                    temp_open = round(float(temp_open) + float(batch_open_delt), 1)
                                    temp_close = round(float(temp_close) + float(batch_close_delt), 1)
                                    temp_volume = int(float(temp_volume) + float(batch_volume_delt))
                                    if temp_volume < 1:
                                        temp_volume = 1
                                    batch_amount_total -= 1

                                    # 写入批量
                                    # 分多空
                                    if float(temp_open) < float(temp_close):
                                        # 这是多单
                                        direction = '多'
                                    else:
                                        # 这是空单
                                        direction = '空'

                                    insert_temp_list_strategy()

                            elif batch_type == '等比':
                                batch_open_delt = temp_batch['开仓价格间隔']
                                batch_close_delt = temp_batch['平仓价格间隔']
                                batch_volume_delt = temp_batch['仓位间隔']
                                batch_amount_total = temp_batch['总单数']

                                # 先写入普通策略
                                # 分多空
                                if float(temp_open) < float(temp_close):
                                    # 这是多单
                                    direction = '多'
                                else:
                                    # 这是空单
                                    direction = '空'

                                insert_temp_list_strategy()

                                # 再处理批量策略
                                # int 去尾取整
                                batch_amount_total = int(
                                    float(batch_amount_total))
                                while batch_amount_total > 1:
                                    temp_open = round(float(temp_open) * (1 + float(batch_open_delt) / 100), 1)
                                    temp_close = round(float(temp_close) * (1 + float(batch_close_delt) / 100), 1)
                                    temp_volume = int(float(temp_volume) * (1 + float(batch_volume_delt) / 100))
                                    if temp_volume < 1:
                                        temp_volume = 1
                                    batch_amount_total -= 1

                                    # 写入批量
                                    # 分多空
                                    if float(temp_open) < float(temp_close):
                                        # 这是多单
                                        direction = '多'
                                    else:
                                        # 这是空单
                                        direction = '空'

                                    insert_temp_list_strategy()

                    return temp_list_strategy

                list_strategy_creating = analysis_creating(data_in)
                for strategy in list_strategy_creating:
                    list_strategy.append(strategy)

            # 计算web单的影响
            if cal_status_web == 'True':
                # 查非api委托
                sql = "SELECT price,volume,direction,offset,trade_volume FROM orders_active where client_name= '%s' and contract = '%s' and order_source != 'api' " % (client_name, contract)
                results = tools.mysql_short_get(sql)

                for result in results:
                    price = result[0]
                    volume = result[1]
                    direction = result[2]
                    offset = result[3]
                    trade_volume = result[4]

                    # 伪造策略信息
                    def insert_list_strategy():
                        list_strategy.append(
                            {'open': temp_open, 'close': temp_close, 'stop_loss': stop_loss,
                             'stop_profit': stop_profit,
                             'volume': temp_volume, 'amount_cycle': 0, 'stop_amount_cycle': 1,
                             'direction': temp_direction,
                             'trade_volume': temp_trade_volume})

                    if direction == 'buy' and offset == 'open':
                        temp_open = price
                        temp_close = highest_price
                        stop_loss = lowest_price
                        stop_profit = highest_price
                        temp_volume = volume
                        temp_direction = '多'
                        temp_trade_volume = trade_volume
                        insert_list_strategy()

                    elif direction == 'buy' and offset == 'close':
                        temp_open = lowest_price
                        temp_close = price
                        stop_loss = lowest_price
                        stop_profit = highest_price
                        temp_volume = volume
                        temp_direction = '多'
                        temp_trade_volume = trade_volume
                        insert_list_strategy()

                    elif direction == 'sell' and offset == 'open':
                        temp_open = price
                        temp_close = lowest_price
                        stop_loss = highest_price
                        stop_profit = lowest_price
                        temp_volume = volume
                        temp_direction = '空'
                        temp_trade_volume = trade_volume
                        insert_list_strategy()

                    elif direction == 'sell' and offset == 'close':
                        temp_open = highest_price
                        temp_close = price
                        stop_loss = highest_price
                        stop_profit = lowest_price
                        temp_volume = volume
                        temp_direction = '空'
                        temp_trade_volume = trade_volume
                        insert_list_strategy()

            # 数据清洗，整理list_strategy
            for strategy in list_strategy:
                # 修正止盈
                if strategy['stop_profit'] == 'None':
                    if strategy['direction'] == '多':
                        strategy['stop_profit'] = highest_price
                    else:
                        strategy['stop_profit'] = lowest_price
                else:
                    strategy['stop_profit'] = float(strategy['stop_profit'])

                # 修正止损
                if strategy['stop_loss'] == 'None':
                    if strategy['direction'] == '多':
                        strategy['stop_loss'] = lowest_price
                    else:
                        strategy['stop_loss'] = highest_price
                else:
                    strategy['stop_loss'] = float(strategy['stop_loss'])

                # 修正参数类型
                strategy['open'] = float(strategy['open'])
                strategy['close'] = float(strategy['close'])
                strategy['volume'] = float(strategy['volume'])
                strategy['amount_cycle'] = float(strategy['amount_cycle'])
                strategy['stop_amount_cycle'] = float(
                    strategy['stop_amount_cycle'])
                strategy['trade_volume'] = float(strategy['trade_volume'])

            sql = "SELECT 上终止,下终止 FROM information_client where name='%s' and contract='%s' " % (client_name, contract)
            results = tools.mysql_short_get(sql)

            end_up = results[0][0]
            end_down = results[0][1]
            # 消除上终止影响
            if end_up == 'None':
                pass
            else:
                end_up = float(end_up)
                for strategy in list_strategy:
                    if strategy['direction'] == '多':
                        strategy['stop_profit'] = min(
                            [end_up, strategy['stop_profit']])
                    else:
                        strategy['stop_loss'] = min(
                            [end_up, strategy['stop_loss']])

            if end_down == 'None':
                pass
            else:
                end_down = float(end_down)
                for strategy in list_strategy:
                    if strategy['direction'] == '多':
                        strategy['stop_loss'] = max(
                            [end_down, strategy['stop_loss']])
                    else:
                        strategy['stop_profit'] = max(
                            [end_down, strategy['stop_profit']])

            paramters = {
                'list_strategy': list_strategy,
                'price_new': price_new,
                'pur_value': pur_value,
                'contract': contract,
            }

            logger_content.info(f'请求计算盈亏,{paramters}')
            response = risk_cal.cal_profit_and_loss(paramters)
            logger_content.info(f'response,{response}')

            data_out = response['data']
            buy_straight_up = data_out['多单']['直涨']
            buy_straight_down = data_out['多单']['直跌']
            buy_cycle_up = data_out['多单']['循涨']
            buy_cycle_down = data_out['多单']['循跌']
            sell_straight_up = data_out['空单']['直涨']
            sell_straight_down = data_out['空单']['直跌']
            sell_cycle_up = data_out['空单']['循涨']
            sell_cycle_down = data_out['空单']['循跌']
            account_straight_up = data_out['账户']['直涨']
            account_straight_down = data_out['账户']['直跌']
            account_cycle_up = data_out['账户']['循涨']
            account_cycle_down = data_out['账户']['循跌']

            return data_out
        except:
            # print(traceback.format_exc())
            logger_content.info(traceback.format_exc())

    temp_result = cal_profit_loss(
        client_name=data_in['client'],
        contract=data_in['contract'],
        data_in=data_in,
        cal_status_running=in_cal_status_running,
        cal_status_unrun=in_cal_status_unrun,
        cal_status_creating=in_cal_status_creatingcal_status_creating,
        cal_status_web=in_cal_status_web)

    try:
        # 填充数据
        straight_up = temp_result['账户']['直涨']
        straight_down = temp_result['账户']['直跌']
        cycle_up = temp_result['账户']['循涨']
        cycle_down = temp_result['账户']['循跌']

        straight_up = tools.get_display_number(
            number=straight_up, contract=in_contract)
        straight_down = tools.get_display_number(
            number=straight_down, contract=in_contract)
        cycle_up = tools.get_display_number(
            number=cycle_up, contract=in_contract)
        cycle_down = tools.get_display_number(
            number=cycle_down, contract=in_contract)

        temp_tict = {}
        temp_tict['max_profit_and_loss_data'] = {
            'c1': straight_up,
            'c2': cycle_up,
            'c3': straight_down,
            'c4': cycle_down}

        temp_return = cal_liquidation(in_client, in_contract, data_in)
        temp_tict['liquidation_buy'] = str(temp_return[0])
        temp_tict['liquidation_sell'] = str(temp_return[1])
    except:
        print(traceback.format_exc())
        temp_tict = {}
        temp_tict['max_profit_and_loss_data'] = {
            'c1': '计算失败', 'c2': '计算失败', 'c3': '计算失败', 'c4': '计算失败'}
        temp_tict['liquidation_buy'] = '计算失败'
        temp_tict['liquidation_sell'] = '计算失败'

    return respond({'code': 1000, 'data': temp_tict, 'msg': '强平计算成功'})


@app.route("/quant/trade/get_liquidation_pro", methods=['POST'])
def quant_trade_get_liquidation_pro():
    data_in = g.data_in

    client = data_in['client']
    contract = data_in['contract']

    config_server_name = config['server_name']
    config_server_exchange = config['server_exchange']
    config_real_trading = config['real_trading']
    config_db_info = config['db_info']
    config_loggerbackupcount = config['loggerbackupcount']
    config_ding_info = config['ding_info']
    config_urls = config['exchange'][config_server_exchange][config_real_trading]['urls']
    config_contracts = config['exchange'][config_server_exchange][config_real_trading]['contracts']
    config_liquidation = config['exchange'][config_server_exchange][config_real_trading]['liquidation']
    config_rest_errors = config['exchange'][config_server_exchange]['rest_errors']

    # print(f'config_contracts:{config_contracts}')
    # print(f'config_liquidation:{config_liquidation}')

    # 转换合约为强平参数的写法
    if 'SWAP' in contract:
        contract_type = contract
    else:
        contract_type = f"{contract.split('-')[0]}-{contract.split('-')[1]}-FUTURES"

    # 请求样例
    # strategyList = [
    #     {'id': '1', 'direction': '多', 'open': '53700', 'close': '54100', 'volume': '400', 'orderId': '1243143'},
    #     {'id': '2', 'direction': '多', 'open': '53600', 'close': '54000', 'volume': '100', 'orderId': ''},
    #     {'id': '3', 'direction': '多', 'open': '53500', 'close': '53900', 'volume': '100', 'orderId': ''},
    #     {'id': '4', 'direction': '多', 'open': '53400', 'close': '53800', 'volume': '100', 'orderId': ''},
    #     {'id': '5', 'direction': '多', 'open': '53300', 'close': '53700', 'volume': '100', 'orderId': ''},
    #     {'id': '6', 'direction': '多', 'open': '53200', 'close': '53600', 'volume': '100', 'orderId': ''},
    #     {'id': '100', 'direction': '空', 'open': '54200', 'close': '53600', 'volume': '500', 'orderId': '433636'},
    #     {'id': '100', 'direction': '空', 'open': '54300', 'close': '53700', 'volume': '200', 'orderId': ''},
    #     {'id': '100', 'direction': '空', 'open': '54400', 'close': '53800', 'volume': '200', 'orderId': ''},
    #     {'id': '100', 'direction': '空', 'open': '54500', 'close': '53900', 'volume': '100', 'orderId': ''},
    #     {'id': '100', 'direction': '空', 'open': '54600', 'close': '54000', 'volume': '100', 'orderId': ''}
    # 若为未持仓 orderId为空,若有仓位 orderId非空
    # ]
    # serviceChargeRate = '0.0002'  # 手续费率
    # parValue = '100'  # 面值
    # multiple = '125'  # 杠杆倍数
    # upPosition = '400'  # 多方持仓
    # upAveragePositionPrice = '53700'  # 多方持仓均价
    # downPosition = '500'  # 空方持仓
    # downAveragePositionPrice = '54200'  # 空方持仓均价
    # staticBalance = '0.1'  # 静态权益
    # shortNumber = '5'  # 空方策略数
    # buyNumber = '6'  # 多方策略数

    lowest_price = 0.1 ** tools.get_contract_precision(contract)
    highest_price = 1000000

    # 查询手续费率
    sql = "SELECT maker_fee,taker_fee FROM information_client where name = '%s' and contract = '%s' " % (client, contract)
    results = tools.mysql_short_get(sql)

    maker_fee = float(results[0][0])
    taker_fee = float(results[0][1])

    # 面值
    parValue = config_contracts[contract_type]['parvalue']
    # 调整系数
    config_liquidation = config_liquidation[contract_type]

    sql = "SELECT swap_buy_volume,swap_buy_cost_open,swap_sell_volume,swap_sell_cost_open,swap_margin_balance,swap_profit_unreal,swap_buy_lever_rate,当前强平点 FROM information_client where name= '%s' and contract = '%s' " % (client, contract)  # SQL 查询语句
    results = tools.mysql_short_get(sql)

    # 多方向持仓数量
    upPosition = float(results[0][0])
    # 多方向持仓均价
    upAveragePositionPrice = float(results[0][1])
    # 空方向持仓数量
    downPosition = float(results[0][2])
    # 空方向持仓均价
    downAveragePositionPrice = float(results[0][3])
    # 静态权益=账户权益-未实现盈亏
    margin_balance = float(results[0][4])
    profit_unreal = float(results[0][5])
    staticBalance = float(results[0][4]) - float(results[0][5])
    # 杠杆倍数
    multiple = float(results[0][6])
    liquidation_exchange = results[0][7]

    # 获取最新价格,保存为字典
    dict_price = tools.get_price_dict()
    price_latest = {'市价': dict_price[contract]['price_new'], '指数价': dict_price[contract]['price_index'], '标记价': dict_price[contract]['price_mark']}

    # 开始构件策略数据
    strategyList = []
    buyNumber = 0
    shortNumber = 0

    buy_max_volume = 0
    sell_max_volume = 0
    # {'id': '1', 'direction': '多', 'open': '53700', 'close': '54100', 'volume': '400', 'orderId': '1243143'},

    # 获取策略
    sql = "SELECT strategy_id,open,close,direction,volume,inposition,stop_profit,stop_loss,strategy_status,stop_profit_type,stop_loss_type,average_opening_price,group_id,amount_cycle,stop_amount_cycle FROM strategy_parameter_cycle_run where client_name='%s' and contract_type='%s' and strategy_status != '未启动'   " % (client, contract)  # SQL 查询语句
    results = tools.mysql_short_get(sql)
    for result in results:
        temp_dict = {}
        temp_dict['id'] = result[0]
        temp_dict['open'] = result[1]
        temp_dict['close'] = result[2]
        temp_dict['direction'] = result[3]
        temp_dict['volume'] = result[4]
        temp_dict['inposition'] = result[5]
        temp_dict['stop_profit'] = result[6]
        temp_dict['stop_loss'] = result[7]
        temp_dict['strategy_status'] = result[8]
        temp_dict['stop_profit_type'] = result[9]
        temp_dict['stop_loss_type'] = result[10]
        temp_dict['group_id'] = result[12]
        temp_dict['amount_cycle'] = float(result[13])
        temp_dict['stop_amount_cycle'] = float(result[14])

        for _ in ['_多等待执行', '_空等待执行', '_多异常', '_空异常', '_多被动', '_空被动', '_多主动', '_空主动']:
            if _ in temp_dict['group_id']:

                msg = '策略中存在"等待执行策略"/"异常策略"/"主动平仓策略"/"被动平仓策略"，无法计算'

                result = {'直涨直跌': {'直涨': {'name': '', 'msg': msg, 'value': '无法计算'}, '直跌': {'name': '', 'msg': msg, 'value': '无法计算'}},
                          '原始': {'直涨': {'name': '', 'msg': msg, 'value': '无法计算'}, '直跌': {'name': '', 'msg': msg, 'value': '无法计算'}},
                          '先涨': {'多盈': {'直涨': {'name': '', 'msg': msg, 'value': '无法计算'}, '直跌': {'name': '', 'msg': msg, 'value': '无法计算'}}, '空损': {'直涨': {'name': '', 'msg': msg, 'value': '无法计算'}, '直跌': {'name': '', 'msg': msg, 'value': '无法计算'}}},
                          '先跌': {'空盈': {'直涨': {'name': '', 'msg': msg, 'value': '无法计算'}, '直跌': {'name': '', 'msg': msg, 'value': '无法计算'}}, '多损': {'直涨': {'name': '', 'msg': msg, 'value': '无法计算'}, '直跌': {'name': '', 'msg': msg, 'value': '无法计算'}}},
                          '交易所强平': {'name': '', 'msg': msg, 'value': '无法计算'},
                          '止盈止损价格': {'多盈': '--', '空损': '--', '多损': '--', '空盈': '--'}}

                return respond({'code': 1000, 'data': result, 'msg': msg})

        temp_dict['average_opening_price'] = float(temp_dict['open']) if result[11] == 'None' else float(result[11])

        temp_dict['orderId'] = '' if float(result[5]) == 0 else '1'
        if temp_dict['direction'] == '多':
            buyNumber += 1
            buy_max_volume = buy_max_volume + float(temp_dict['volume'])
        else:
            shortNumber += 1
            sell_max_volume = sell_max_volume + float(temp_dict['volume'])

        strategyList.append(temp_dict)

    # 修正上下终止影响
    # 获取数据
    sql = "SELECT 上终止,下终止 FROM information_client where name='%s' and contract='%s' " % (client, contract)  # SQL 查询语句
    results = tools.mysql_short_get(sql)
    end_up = results[0][0]
    end_down = results[0][1]
    # 消除上终止影响
    if end_up == 'None':
        pass
    else:
        end_up = float(end_up)
        for strategy in strategyList:
            if strategy['direction'] == '多':
                if strategy['stop_profit'] == 'None':
                    strategy['stop_profit'] = end_up
                else:
                    strategy['stop_profit'] = min([end_up, float(strategy['stop_profit'])])

            if strategy['direction'] == '空':
                if strategy['stop_loss'] == 'None':
                    strategy['stop_loss'] = end_up
                else:
                    strategy['stop_loss'] = min([end_up, float(strategy['stop_loss'])])

    if end_down == 'None':
        pass
    else:
        end_down = float(end_down)
        for strategy in strategyList:
            if strategy['direction'] == '多':
                if strategy['stop_loss'] == 'None':
                    strategy['stop_loss'] = end_down
                else:
                    strategy['stop_loss'] = max([end_down, float(strategy['stop_loss'])])
            if strategy['direction'] == '空':
                if strategy['stop_profit'] == 'None':
                    strategy['stop_profit'] = end_down
                else:
                    strategy['stop_profit'] = max([end_down, float(strategy['stop_profit'])])

    paramters = {
        'contract': contract,
        'price': price_latest,
        # 'contract_type': contract_type,
        'strategy_list': strategyList,
        'maker_fee': maker_fee,
        'taker_fee': taker_fee,
        'face_value': parValue,
        'leverage': multiple,
        'long_position': upPosition,
        'long_average_price': upAveragePositionPrice,
        'short_position': downPosition,
        'short_average_price': downAveragePositionPrice,
        'margin_balance': margin_balance,
        'static_balance': staticBalance,
        'profit_unreal': profit_unreal,
        'count_of_short_strategy': shortNumber,
        'count_of_long_strategy': buyNumber,
        'tick_size': 0.1 ** tools.get_contract_precision(contract),
        'config_liquidation': config_liquidation,
        'liquidation_exchange': liquidation_exchange
    }

    data_qiangping = paramters

    # 开始计算

    data_in = {}

    # 处理所需盈亏数据
    data_in["contract"] = data_qiangping["contract"]
    data_in["face_value"] = data_qiangping["face_value"]
    data_in["maker_fee"] = data_qiangping["maker_fee"]
    data_in["price"] = data_qiangping["price"]
    data_in["taker_fee"] = data_qiangping["taker_fee"]

    # 处理所需强平数据
    data_in["config_liquidation"] = data_qiangping["config_liquidation"]
    data_in["count_of_long_strategy"] = data_qiangping["count_of_long_strategy"]
    data_in["count_of_short_strategy"] = data_qiangping["count_of_short_strategy"]
    data_in["leverage"] = data_qiangping["leverage"]
    data_in["long_average_price"] = data_qiangping["long_average_price"]
    data_in["short_average_price"] = data_qiangping["short_average_price"]
    data_in["long_position"] = data_qiangping["long_position"]
    data_in["short_position"] = data_qiangping["short_position"]
    data_in["static_balance"] = data_qiangping["static_balance"]
    data_in["strategy_list"] = data_qiangping["strategy_list"]
    data_in["tick_size"] = data_qiangping["tick_size"]
    data_in["profit_unreal"] = data_qiangping["profit_unreal"]

    # data_in["liquidation_exchange"] = data_qiangping["liquidation_exchange"]

    def calc_liquidation_point(data_in):

        if "USDT" in data_in["contract"]:
            standard = "USDT"
        else:
            standard = "USD"
        lp = liquidation(
            price_list=data_in["price"],
            static_balance=float(data_in["static_balance"]),
            profit_unreal=float(data_in["profit_unreal"]),
            long_position=float(data_in["long_position"]),
            short_position=float(data_in["short_position"]),
            long_average_price=float(data_in["long_average_price"]),
            short_average_price=float(data_in["short_average_price"]),
            strategy_list=data_in["strategy_list"],
            standard=standard,
            face_value=float(data_in["face_value"]),
            taker_fee=float(data_in["taker_fee"]),
            maker_fee=float(data_in["maker_fee"]),
            tick_size=data_in["tick_size"],
            config_liquidation=data_in["config_liquidation"],
            leverage=data_in["leverage"],
            # liquidation_exchange=float(data_in["liquidation_exchange"]),
        )

        def print(*arg, **kwargs):

            for x in arg:
                lp.logs.append(x)


        # print(data_in["strategy_list"])

        # lp.virtual.output_strategy()

        print("\n\n\n--------------------------next-----------------------------\n交易所强平")
        msg, value = lp.exchange_liquidation()
        lp.result["交易所强平"] = {"name": "交易所强平", "msg": msg, "value": value}

        lp.refresh_virtual()
        print("--------------------------next-----------------------------\n原始直涨")
        msg, value = lp.dont_trigger_stop_then("up")
        lp.result["原始"]["直涨"] = {"name": "不触发任何止盈止损的直涨", "msg": msg, "value": value}

        lp.refresh_virtual()

        print("--------------------------next-----------------------------\n原始直跌")
        msg, value = lp.dont_trigger_stop_then("down")
        lp.result["原始"]["直跌"] = {"name": "不触发任何止盈止损的直跌", "msg": msg, "value": value}

        lp.refresh_virtual()
        print("--------------------------next-----------------------------\n直涨")
        msg, value = lp.straight_up()
        lp.result["直涨直跌"]["直涨"] = {"name": "直涨", "msg": msg, "value": value}

        lp.refresh_virtual()

        print("--------------------------next-----------------------------\n直跌")
        msg, value = lp.straight_down()
        lp.result["直涨直跌"]["直跌"] = {"name": "直跌", "msg": msg, "value": value}

        lp.refresh_virtual()

        print("--------------------------next-----------------------------\n触发多方止盈后直涨")
        print(lp.result["直涨直跌"]["直涨"]["value"])
        print(lp.long_max_profit)
        if lp.result["直涨直跌"]["直涨"]["value"] != "--" and lp.long_max_profit != "--" and lp.long_max_profit > lp.result["直涨直跌"]["直涨"]["value"]:
            msg = f"多方触发止盈({lp.long_max_profit})过程中强平，无法计算"
            value = "--"
        elif lp.result["直涨直跌"]["直涨"]["value"] != "--" and lp.long_max_profit != "--" and lp.long_max_profit <= lp.result["直涨直跌"]["直涨"]["value"] and lp.long_max_profit > lp._price:
            value = lp.result['直涨直跌']['直涨']['value']
            msg = f"触发多方止盈价({lp.long_max_profit})后直涨强平点：{value}"
        else:
            msg, value = lp.trigger_stop_then("long", "profit", "up")

        lp.result["先涨"]["多盈"]["直涨"] = {"name": "触发多方止盈后直涨", "msg": msg, "value": value}
        lp.refresh_virtual()

        print("--------------------------next-----------------------------\n触发多方止盈后直跌")
        if lp.result["直涨直跌"]["直涨"]["value"] != "--" and lp.long_max_profit != "--" and lp.long_max_profit > lp.result["直涨直跌"]["直涨"]["value"]:
            msg = f"多方触发止盈({lp.long_max_profit})过程中强平，无法计算"
            value = "--"
        else:
            msg, value = lp.trigger_stop_then("long", "profit", "down")

        lp.result["先涨"]["多盈"]["直跌"] = {"name": "触发多方止盈后直跌", "msg": msg, "value": value}
        lp.refresh_virtual()

        print("--------------------------next-----------------------------\n触发多方止损后直涨")
        if lp.result["直涨直跌"]["直跌"]["value"] != "--" and lp.long_min_loss != "--" and lp.long_min_loss < lp.result["直涨直跌"]["直跌"]["value"]:
            msg = f"多方触发止损({lp.long_min_loss})过程中强平，无法计算"
            value = "--"
        else:
            msg, value = lp.trigger_stop_then("long", "loss", "up")

        lp.result["先跌"]["多损"]["直涨"] = {"name": "触发多方止损后直涨", "msg": msg, "value": value}
        lp.refresh_virtual()

        print("--------------------------next-----------------------------\n触发多方止损后直跌")
        if lp.result["直涨直跌"]["直跌"]["value"] != "--" and lp.long_min_loss != "--" and lp.long_min_loss < lp.result["直涨直跌"]["直跌"]["value"]:
            msg = f"多方触发止损({lp.long_min_loss})过程中强平，无法计算"
            value = "--"
        elif lp.result["直涨直跌"]["直跌"]["value"] != "--" and lp.long_min_loss != "--" and lp.long_min_loss >= lp.result["直涨直跌"]["直跌"]["value"] and lp.long_min_loss < lp._price:
            value = lp.result['直涨直跌']['直跌']['value']
            msg = f"触发多方止损价({lp.long_min_loss})后直跌强平点：{value}"
        else:
            msg, value = lp.trigger_stop_then("long", "loss", "down")

        lp.result["先跌"]["多损"]["直跌"] = {"name": "触发多方止损后直跌", "msg": msg, "value": value}
        lp.refresh_virtual()

        print("--------------------------next-----------------------------\n触发空方止盈后直涨")
        if lp.result["直涨直跌"]["直跌"]["value"] != "--" and lp.short_min_profit != "--" and lp.short_min_profit < lp.result["直涨直跌"]["直跌"]["value"]:
            msg = f"空方触发止盈({lp.short_min_profit})过程中强平，无法计算"
            value = "--"
        else:
            msg, value = lp.trigger_stop_then("short", "profit", "up")
        lp.result["先跌"]["空盈"]["直涨"] = {"name": "触发空方止盈后直涨", "msg": msg, "value": value}

        lp.refresh_virtual()

        print("--------------------------next-----------------------------\n触发空方止盈后直跌")
        if lp.result["直涨直跌"]["直跌"]["value"] != "--" and lp.short_min_profit != "--" and lp.short_min_profit < lp.result["直涨直跌"]["直跌"]["value"]:
            msg = f"空方触发止盈({lp.short_min_profit})过程中强平，无法计算"
            value = "--"
        elif lp.result["直涨直跌"]["直跌"]["value"] != "--" and lp.short_min_profit != "--" and lp.short_min_profit >= lp.result["直涨直跌"]["直跌"]["value"] and lp.short_min_profit < lp._price:
            value = lp.result['直涨直跌']['直跌']['value']
            msg = f"触发空方止盈价({lp.short_min_profit})后直跌强平点：{value}"
        else:
            msg, value = lp.trigger_stop_then("short", "profit", "down")
        lp.result["先跌"]["空盈"]["直跌"] = {"name": "触发空方止盈后直跌", "msg": msg, "value": value}

        lp.refresh_virtual()

        print("--------------------------next-----------------------------\n触发空方止损后直涨")
        if lp.result["直涨直跌"]["直涨"]["value"] != "--" and lp.short_max_loss != "--" and lp.short_max_loss > lp.result["直涨直跌"]["直涨"]["value"]:
            msg = f"空方触发止损({lp.short_max_loss})过程中强平，无法计算"
            value = "--"
        elif lp.result["直涨直跌"]["直涨"]["value"] != "--" and lp.short_max_loss != "--" and lp.short_max_loss <= lp.result["直涨直跌"]["直涨"]["value"] and lp.short_max_loss > lp._price:
            value = lp.result['直涨直跌']['直涨']['value']
            msg = f"触发空方止损价({lp.short_max_loss})后直涨强平点：{value}"
        else:
            msg, value = lp.trigger_stop_then("short", "loss", "up")
        lp.result["先涨"]["空损"]["直涨"] = {"name": "触发空方止损后直涨", "msg": msg, "value": value}

        lp.refresh_virtual()

        print("--------------------------next-----------------------------\n触发空方止损后直跌")
        if lp.result["直涨直跌"]["直涨"]["value"] != "--" and lp.short_max_loss != "--" and lp.short_max_loss > lp.result["直涨直跌"]["直涨"]["value"]:
            msg = f"空方触发止损({lp.short_max_loss})过程中强平，无法计算"
            value = "--"
        else:
            msg, value = lp.trigger_stop_then("short", "loss", "down")
        lp.result["先涨"]["空损"]["直跌"] = {"name": "触发空方止损后直跌", "msg": msg, "value": value}

        lp.refresh_virtual()

        print("--------------------------next-----------------------------")
        lp.virtual.output_attr()
        # lp.virtual.output_strategy()
        return lp.result,lp.logs

    result,logs = calc_liquidation_point(data_in)
    # print(data_in["static_balance"])

    return respond({'code': 1000, 'data': result, 'logs_calc': logs, 'msg': '强平计算成功'})
    # return respond({'code': 1001, 'data': result, 'msg': '计算出错'})


# 2.3.2 新建策略
@app.route("/quant/trade/insert_strategy", methods=['POST'])
def quant_trade_insert_unrun():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']

    in_strategy = data_in['strategy']
    in_open = data_in['open']
    in_close = data_in['close']
    in_volume = data_in['volume']
    in_run_or_unrun = data_in['run_or_unrun']  # run_or_unrun 可选参数为 run/unrun
    in_basic_id = data_in['basic_id']
    in_batch_id = data_in['batch_id']

    type_check, msg, in_open = typecheck.is_posfloat(in_open, tools.get_contract_precision(in_contract))
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'开仓价格||{msg}'})

    type_check, msg, in_close = typecheck.is_posfloat(in_close, tools.get_contract_precision(in_contract))
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'平仓价格||{msg}'})

    type_check, msg, in_volume = typecheck.is_posint(in_volume)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'仓位||{msg}'})

    # 检查止盈止损
    sql = "SELECT stop_loss,stop_loss_type,stop_profit,stop_profit_type,stop_amount_cycle,stop_time,stop_time_type,stop_time_time_or_len,stop_time_len,stop_loss_price_type,stop_profit_price_type FROM strategy_parameter_cycle_preset WHERE strategy_id='%s' " % (in_basic_id)
    results1 = tools.mysql_short_get(sql)

    temp_stop_loss = results1[0][0]
    temp_stop_loss_type = results1[0][1]
    temp_stop_profit = results1[0][2]
    temp_stop_profit_type = results1[0][3]
    temp_stop_amount_cycle = results1[0][4]
    temp_stop_time = results1[0][5]
    temp_stop_time_type = results1[0][6]
    temp_stop_time_time_or_len = results1[0][7]
    temp_stop_time_len = results1[0][8]
    stop_loss_price_type = results1[0][9]
    stop_profit_price_type = results1[0][10]

    dict_price = tools.get_price_dict()

    # 判断方向
    if in_close > in_open:  # '多'
        # 检查止损
        if temp_stop_loss == 'None':
            pass
        else:
            if float(temp_stop_loss) >= tools.get_price(dict_price=dict_price, contract_code=in_contract, price_type=stop_loss_price_type):
                return respond({'code': 1001, 'data': '', 'msg': f'看多止损价需小于{stop_loss_price_type}'})
        # 检查止盈
        if temp_stop_profit == 'None':
            pass
        else:
            if float(temp_stop_profit) <= tools.get_price(dict_price=dict_price, contract_code=in_contract, price_type=stop_profit_price_type):
                return respond({'code': 1001, 'data': '', 'msg': f'看多止盈价需大于{stop_loss_price_type}'})
    elif in_open > in_close:  # '空'
        # 检查止损
        if temp_stop_loss == 'None':
            pass
        else:
            if float(temp_stop_loss) <= tools.get_price(dict_price=dict_price, contract_code=in_contract, price_type=stop_loss_price_type):
                return respond({'code': 1001, 'data': '', 'msg': f'看空止损价需大于{stop_loss_price_type}'})
        # 检查止盈
        if temp_stop_profit == 'None':
            pass
        else:
            if float(temp_stop_profit) >= tools.get_price(dict_price=dict_price, contract_code=in_contract, price_type=stop_profit_price_type):
                return respond({'code': 1001, 'data': '', 'msg': f'看空止盈价需小于{stop_loss_price_type}'})
    else:
        return respond({'code': 1001, 'data': '', 'msg': '开仓价格不能等于平仓价格'})

    # 检查终止时间
    if temp_stop_time_time_or_len == 'time':
        if float(temp_stop_time) < time.time():
            return respond({'code': 1001, 'data': '', 'msg': '终止时间需大于当前时间'})

    if in_batch_id == 'None':
        # 查基础参数
        db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)

        cursor = db.cursor()
        sql = "SELECT stop_loss,stop_loss_type,stop_profit,stop_profit_type,stop_amount_cycle,stop_time,stop_time_type,stop_time_time_or_len,stop_time_len,stop_loss_price_type,stop_profit_price_type FROM strategy_parameter_cycle_preset WHERE strategy_id='%s' " % (
            in_basic_id)
        cursor.execute(sql)  # 执行SQL语句
        results1 = cursor.fetchall()  # 获取所有记录列表

        temp_open = in_open
        temp_close = in_close
        temp_volume = in_volume
        temp_stop_loss = results1[0][0]
        temp_stop_loss_type = results1[0][1]
        temp_stop_profit = results1[0][2]
        temp_stop_profit_type = results1[0][3]
        temp_stop_amount_cycle = results1[0][4]
        temp_stop_time = results1[0][5]
        temp_stop_time_type = results1[0][6]
        temp_stop_time_time_or_len = results1[0][7]
        temp_stop_time_len = results1[0][8]
        stop_loss_price_type = results1[0][9]
        stop_profit_price_type = results1[0][10]

        if len(temp_stop_time) == 0:
            temp_stop_time = " 'None' "
        if len(temp_stop_time_len) == 0:
            temp_stop_time_len = " 'None' "
        if len(stop_loss_price_type) == 0:
            temp_stop_time_len = " 'None' "
        if len(stop_profit_price_type) == 0:
            temp_stop_time_len = " 'None' "

        temp_batch = "{'批量类型':'None'}"

        strategy_detail = "{'open':" + str(temp_open) + ",'close':" + str(
            temp_close) + ",'volume':" + str(temp_volume) + ",'stop_loss':" + str(
            temp_stop_loss) + ",'stop_loss_type':'" + str(temp_stop_loss_type) + "','stop_profit':" + str(
            temp_stop_profit) + ",'stop_profit_type':'" + str(
            temp_stop_profit_type) + "','stop_amount_cycle':" + str(
            temp_stop_amount_cycle) + ",'stop_time':" + str(
            temp_stop_time) + ",'stop_time_type':'" + str(
            temp_stop_time_type) + "','stop_time_time_or_len':'" + str(
            temp_stop_time_time_or_len) + "','stop_time_len':" + str(temp_stop_time_len) + ",'stop_loss_price_type':'" + str(stop_loss_price_type) + "','stop_profit_price_type':'" + str(stop_profit_price_type) + "','batch':" + str(
            temp_batch) + "}"
    elif in_batch_id != 'None':
        # 查基础参数
        db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
        cursor = db.cursor()
        sql = "SELECT stop_loss,stop_loss_type,stop_profit,stop_profit_type,stop_amount_cycle,stop_time,stop_time_type,stop_time_time_or_len,stop_time_len,stop_loss_price_type,stop_profit_price_type FROM strategy_parameter_cycle_preset WHERE strategy_id='%s' " % (
            in_basic_id)
        cursor.execute(sql)  # 执行SQL语句
        results1 = cursor.fetchall()  # 获取所有记录列表

        sql = "SELECT batch FROM strategy_parameter_cycle_preset WHERE strategy_id='%s' " % (
            in_batch_id)
        cursor.execute(sql)  # 执行SQL语句
        results2 = cursor.fetchall()  # 获取所有记录列表

        temp_open = in_open
        temp_close = in_close
        temp_volume = in_volume
        temp_stop_loss = results1[0][0]
        temp_stop_loss_type = results1[0][1]
        temp_stop_profit = results1[0][2]
        temp_stop_profit_type = results1[0][3]
        temp_stop_amount_cycle = results1[0][4]
        temp_stop_time = results1[0][5]
        temp_stop_time_type = results1[0][6]
        temp_stop_time_time_or_len = results1[0][7]
        temp_stop_time_len = results1[0][8]
        stop_loss_price_type = results1[0][9]
        stop_profit_price_type = results1[0][10]
        temp_batch = results2[0][0]

        # 批量生成检查
        batch_type = eval(temp_batch)['批量类型']
        batch_open_delt = float(eval(temp_batch)['开仓价格间隔'])
        batch_close_delt = float(eval(temp_batch)['平仓价格间隔'])
        batch_volume_delt = float(eval(temp_batch)['仓位间隔'])
        batch_amount_total = float(eval(temp_batch)['总单数'])

        # print('batch_close_delt', batch_close_delt)
        # print('batch_amount_total',batch_amount_total)

        if batch_type == '等差':
            last_open = round((temp_open+batch_open_delt*batch_amount_total), tools.get_contract_precision(in_contract))
            last_close = round((temp_close + batch_close_delt * batch_amount_total), tools.get_contract_precision(in_contract))
            last_volume = int(temp_volume + batch_volume_delt * batch_amount_total)
        if batch_type == '等比':
            last_open = round((temp_open * (1+batch_open_delt/100) * (batch_amount_total-1)), tools.get_contract_precision(in_contract))
            last_close = round((temp_close * (1+batch_close_delt/100) * (batch_amount_total-1)), tools.get_contract_precision(in_contract))
            last_volume = int(temp_volume * batch_volume_delt * (batch_amount_total-1))

        direction1 = '多' if temp_open < temp_close else '空'
        direction2 = '多' if last_open < last_close else '空'
        if direction1 != direction2:
            return respond({'code': 1001, 'data': '', 'msg': '批量生成首条与最后一条方向不一致'})
        if last_volume < 1:
            return respond({'code': 1001, 'data': '', 'msg': '批量生成最后一条仓位不能小于0'})


        if len(temp_stop_time) == 0:
            temp_stop_time = " 'None' "
        if len(temp_stop_time_len) == 0:
            temp_stop_time_len = " 'None' "

        # 再构造策略参数字典
        strategy_detail = "{'open':" + str(temp_open) + ",'close':" + str(
            temp_close) + ",'volume':" + str(temp_volume) + ",'stop_loss':" + str(
            temp_stop_loss) + ",'stop_loss_type':'" + str(temp_stop_loss_type) + "','stop_profit':" + str(
            temp_stop_profit) + ",'stop_profit_type':'" + str(
            temp_stop_profit_type) + "','stop_amount_cycle':" + str(
            temp_stop_amount_cycle) + ",'stop_time':" + str(
            temp_stop_time) + ",'stop_time_type':'" + str(
            temp_stop_time_type) + "','stop_time_time_or_len':'" + str(
            temp_stop_time_time_or_len) + "','stop_time_len':" + str(temp_stop_time_len) + ",'stop_loss_price_type':'" + str(stop_loss_price_type) + "','stop_profit_price_type':'" + str(stop_profit_price_type) + "','batch':" + str(
            temp_batch) + "}"

    def create_strategy(in_strategy, in_contract, in_client, in_strategy_detail, in_run_or_unrun):
        db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
        cursor = db.cursor()

        def insert_cycle():
            if float(open) <= 0 or float(open) >= 1000000:
                return 0
            if float(close) <= 0 or float(close) >= 1000000:
                return 0

            if float(open) != float(close):
                sql = "INSERT INTO strategy_parameter_cycle_run (strategy_id_inner,strategy_type,contract_type,client_name,open,close,direction,inposition,volume,points_translation,stop_loss,stop_loss_type,stop_profit,stop_profit_type,amount_cycle,stop_amount_cycle,stop_time,stop_time_type,create_time, strategy_status,stop_time_time_or_len,stop_time_len,group_id,stop_loss_price_type,stop_profit_price_type,counts_of_points_translation,counts_of_points_translation_opposite,average_opening_price) " \
                      "VALUES('%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s')" % \
                      (strategy_id_inner, strategy_type, contract_type, client_name,
                       open, close, direction, inposition, volume, points_translation, stop_loss,
                       stop_loss_type, stop_profit, stop_profit_type, amount_cycle, stop_amount_cycle,
                       stop_time, stop_time_type, time.time(), strategy_status, stop_time_time_or_len,
                       stop_time_len, group_id, stop_loss_price_type, stop_profit_price_type, '0', '0','None')
                cursor.execute(sql)
                db.commit()
                logger_content.info(f'创建策略,{sql}')

        strategy_type = in_strategy
        contract_type = in_contract
        client_name = in_client
        strategy_detail = in_strategy_detail
        run_or_unrun = in_run_or_unrun

        if strategy_type == '循环策略':
            # print(strategy_detail)
            dict_strategy_detail = eval(strategy_detail)
            open = dict_strategy_detail['open']
            close = dict_strategy_detail['close']
            volume = dict_strategy_detail['volume']
            stop_loss = dict_strategy_detail['stop_loss']
            stop_loss_type = dict_strategy_detail['stop_loss_type']
            stop_profit = dict_strategy_detail['stop_profit']
            stop_profit_type = dict_strategy_detail['stop_profit_type']
            stop_amount_cycle = dict_strategy_detail['stop_amount_cycle']
            stop_time = dict_strategy_detail['stop_time']
            stop_time_type = dict_strategy_detail['stop_time_type']

            stop_time_time_or_len = dict_strategy_detail['stop_time_time_or_len']
            stop_time_len = dict_strategy_detail['stop_time_len']
            stop_loss_price_type = dict_strategy_detail['stop_loss_price_type']
            stop_profit_price_type = dict_strategy_detail['stop_profit_price_type']

            batch = dict_strategy_detail['batch']
            batch_type = batch['批量类型']

            if batch_type == 'None':
                # print('当前策略未设置批量')
                # 先写入普通策略
                try:
                    strategy_id_inner = '0'
                    amount_cycle = '0'
                    inposition = '0'
                    points_translation = '0'
                    if run_or_unrun == 'unrun':
                        strategy_status = '未启动'
                    elif run_or_unrun == 'run':
                        strategy_status = '待启动'

                    if float(open) > float(close):
                        direction = '空'
                    else:
                        direction = '多'
                    group_id = '默认' + direction

                    if stop_time_time_or_len == 'None':
                        stop_time = 'None'
                        stop_time_len = 'None'

                        insert_cycle()

                    elif stop_time_time_or_len == 'time':
                        temmp_stop_time = int(float(stop_time) / 1000)
                        stop_time_len = 'None'

                        insert_cycle()
                    elif stop_time_time_or_len == 'len':
                        stop_time = int(
                            float(stop_time_len) * 3600 + time.time())

                        insert_cycle()

                        # print('执行成功')

                except BaseException:
                    logger_content.info(traceback.format_exc())
                    logger_content.info('解析普通策略失败')
                    # print('循环策略-无批量 error')

            elif batch_type == '等差':
                batch_open_delt = batch['开仓价格间隔']
                batch_close_delt = batch['平仓价格间隔']
                batch_volume_delt = batch['仓位间隔']
                batch_amount_total = batch['总单数']

                # print('开仓价格间隔', batch_open_delt)
                # print('平仓价格间隔', batch_close_delt)
                # print('仓位间隔', batch_volume_delt)
                # print('总单数', batch_amount_total)

                # 先写入普通策略
                try:
                    strategy_id_inner = '0'
                    amount_cycle = '0'
                    inposition = '0'
                    points_translation = '0'
                    if run_or_unrun == 'unrun':
                        strategy_status = '未启动'
                    elif run_or_unrun == 'run':
                        strategy_status = '待启动'

                    if float(open) > float(close):
                        direction = '空'
                    else:
                        direction = '多'
                    group_id = '默认' + direction

                    if stop_time_time_or_len == 'None':
                        temp_stop_time = 'None'
                        stop_time_len = 'None'

                        insert_cycle()
                    elif stop_time_time_or_len == 'time':
                        temp_stop_time = int(float(stop_time) / 1000)
                        stop_time_len = 'None'

                        insert_cycle()
                    elif stop_time_time_or_len == 'len':
                        temp_stop_time = int(
                            float(stop_time_len) * 3600 + time.time())

                        insert_cycle()
                    # print('普通策略写入成功')
                except BaseException:
                    # print('普通策略写入失败')
                    logger_content.info(traceback.format_exc())
                    logger_content.info('解析普通策略失败')

                # 再处理批量策略
                # int 去尾取整
                batch_amount_total = int(float(batch_amount_total))
                while batch_amount_total > 1:

                    open = round(float(open) + float(batch_open_delt), tools.get_contract_precision(in_contract))
                    close = round(float(close) + float(batch_close_delt), tools.get_contract_precision(in_contract))

                    volume = int(float(volume) + float(batch_volume_delt))
                    if volume < 1:
                        volume = 1
                    batch_amount_total -= 1

                    try:
                        strategy_id_inner = '0'
                        amount_cycle = '0'
                        inposition = '0'
                        points_translation = '0'
                        if run_or_unrun == 'unrun':
                            strategy_status = '未启动'
                        elif run_or_unrun == 'run':
                            strategy_status = '待启动'

                        if float(open) > float(close):
                            direction = '空'
                        else:
                            direction = '多'
                        group_id = '默认' + direction

                        if stop_time_time_or_len == 'None':
                            temp_stop_time = 'None'
                            stop_time_len = 'None'

                            insert_cycle()
                        elif stop_time_time_or_len == 'time':
                            temp_stop_time = int(float(stop_time) / 1000)
                            stop_time_len = 'None'

                            insert_cycle()
                        elif stop_time_time_or_len == 'len':
                            temp_stop_time = int(
                                float(stop_time_len) * 3600 + time.time())

                            insert_cycle()
                    except BaseException:
                        logger_content.info(traceback.format_exc())
                        logger_content.info('解析普通策略失败')
                        # print('循环策略-无批量 error')

            elif batch_type == '等比':
                batch_open_delt = batch['开仓价格间隔']
                batch_close_delt = batch['平仓价格间隔']
                batch_volume_delt = batch['仓位间隔']
                batch_amount_total = batch['总单数']

                # print('开仓价格间隔', batch_open_delt)
                # print('平仓价格间隔', batch_close_delt)
                # print('仓位间隔', batch_volume_delt)
                # print('批量总单数', batch_amount_total)

                # 先写入普通策略
                try:
                    strategy_id_inner = '0'
                    amount_cycle = '0'
                    inposition = '0'
                    points_translation = '0'
                    if run_or_unrun == 'unrun':
                        strategy_status = '未启动'
                    elif run_or_unrun == 'run':
                        strategy_status = '待启动'

                    if float(open) > float(close):
                        direction = '空'
                    else:
                        direction = '多'
                    group_id = '默认' + direction

                    if stop_time_time_or_len == 'None':
                        temp_stop_time = 'None'
                        stop_time_len = 'None'

                        insert_cycle()
                    elif stop_time_time_or_len == 'time':
                        temp_stop_time = int(float(stop_time) / 1000)
                        stop_time_len = 'None'

                        insert_cycle()
                    elif stop_time_time_or_len == 'len':
                        temp_stop_time = int(
                            float(stop_time_len) * 3600 + time.time())

                        insert_cycle()
                except BaseException:
                    logger_content.info(traceback.format_exc())
                    logger_content.info('解析普通策略失败')
                    # print('循环策略-无批量 error')

                # 再处理批量策略
                # int 去尾取整
                batch_amount_total = int(float(batch_amount_total))
                while batch_amount_total > 1:

                    open = round(float(open) * (1 + float(batch_open_delt) / 100), tools.get_contract_precision(in_contract))
                    close = round(float(close) * (1 + float(batch_close_delt) / 100), tools.get_contract_precision(in_contract))

                    volume = int(float(volume) *
                                 (1 + float(batch_volume_delt) / 100))
                    if volume < 1:
                        volume = 1
                    batch_amount_total -= 1

                    try:
                        strategy_id_inner = '0'
                        amount_cycle = '0'
                        inposition = '0'
                        points_translation = '0'
                        if run_or_unrun == 'unrun':
                            strategy_status = '未启动'
                        elif run_or_unrun == 'run':
                            strategy_status = '待启动'

                        if float(open) > float(close):
                            direction = '空'
                        else:
                            direction = '多'
                        group_id = '默认' + direction

                        if stop_time_time_or_len == 'None':
                            temp_stop_time = 'None'
                            stop_time_len = 'None'

                            insert_cycle()
                        elif stop_time_time_or_len == 'time':
                            temp_stop_time = int(float(stop_time) / 1000)
                            stop_time_len = 'None'

                            insert_cycle()
                        elif stop_time_time_or_len == 'len':
                            temp_stop_time = int(
                                float(stop_time_len) * 3600 + time.time())

                            insert_cycle()
                    except BaseException:
                        logger_content.info(traceback.format_exc())
                        logger_content.info('解析普通策略失败')
                        # print('循环策略-无批量 error')

        db.close()

    create_strategy(in_strategy=in_strategy, in_contract=in_contract, in_client=in_client, in_strategy_detail=strategy_detail, in_run_or_unrun=in_run_or_unrun)

    return respond({'code': 1000, 'data': '', 'msg': '策略创建成功'})


# 2.3.3 启动所选未启动策略(目前仅考虑循环策略）
@app.route("/quant/trade/start_strategy", methods=['POST'])
def quant_trade_start_strategy():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_start_list = data_in['start_list']

    if len(in_start_list) == 0:
        in_start_list = '()'
    in_start_list = eval(in_start_list)

    if isinstance(in_start_list, int):
        db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
        cursor = db.cursor()
        sql = "UPDATE strategy_parameter_cycle_run SET strategy_status='待启动' WHERE strategy_id = '%s' " % (
            in_start_list)
        cursor.execute(sql)
        db.commit()
        db.close()
    else:
        if len(in_start_list) == 0:
            db = pymysql.connect(
                user=mysql_user,
                password=mysql_password,
                host=mysql_host,
                port=mysql_port,
                db=mysql_db,
                charset=mysql_charset)
            cursor = db.cursor()
            sql = "UPDATE strategy_parameter_cycle_run SET strategy_status='%s' WHERE strategy_status='未启动' and client_name = '%s' and contract_type='%s' " % (
                '待启动', in_client, in_contract)
            cursor.execute(sql)
            db.commit()
            db.close()
        else:
            db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
            cursor = db.cursor()
            for strategy_id in in_start_list:
                sql = "UPDATE strategy_parameter_cycle_run SET strategy_status='待启动' WHERE strategy_id = '%s' " % (
                    strategy_id)
                cursor.execute(sql)
                db.commit()
            db.close()

    return respond({'code': 1000, 'data': '', 'msg': '启动成功'})


# 2.3.4 删除所选未启动策略(目前仅考虑循环策略）
@app.route("/quant/trade/delete_strategy", methods=['POST'])
def quant_trade_delete_strategy():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_delete_list = data_in['delete_list']

    if len(in_delete_list) == 0:
        in_delete_list = '()'
    in_delete_list = eval(in_delete_list)

    if isinstance(in_delete_list, int):
        db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
        cursor = db.cursor()
        sql = "DELETE FROM strategy_parameter_cycle_run WHERE strategy_id = '%s' " % (
            in_delete_list)
        cursor.execute(sql)
        db.commit()
        db.close()
    else:
        if len(in_delete_list) == 0:
            db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
            cursor = db.cursor()
            sql = "DELETE FROM strategy_parameter_cycle_run WHERE strategy_status='未启动' and client_name = '%s' and contract_type='%s'" % (
                in_client, in_contract)
            cursor.execute(sql)
            db.commit()
            db.close()
        else:
            db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
            cursor = db.cursor()
            for strategy_id in in_delete_list:
                sql = "DELETE FROM strategy_parameter_cycle_run WHERE strategy_id = '%s' " % (
                    strategy_id)
                cursor.execute(sql)
                db.commit()
            db.close()

    return respond({'code': 1000, 'data': '', 'msg': '删除成功'})


# 2.5.1设置某用户、某合约下终止
@app.route("/quant/trade/update_risk", methods=['POST'])
def quant_trade_update_risk():
    data_in = g.data_in

    in_client_name = data_in['client_name']
    in_contract = data_in['contract']
    in_value = data_in['value']
    in_type = data_in['type']

    if in_type == 'end_up':
        in_end_up_type = data_in['end_up_type']  # 上终止平仓方式
        in_end_up_price_type = data_in['end_up_price_type']  # 上终止价格类型

        if in_end_up_type not in ['主动', '被动']:
            return respond({'code': 1001, 'data': '', 'msg': f'上终止||上终止执行类型不合法'})
        if in_end_up_price_type not in ['市价', '指数价', '标记价']:
            return respond({'code': 1001, 'data': '', 'msg': f'上终止||上终止价格类型不合法'})

        if in_value != 'None':
            type_check, msg, in_value = typecheck.is_posfloat(in_value, tools.get_contract_precision(in_contract))
            if not type_check:
                return respond({'code': 1001, 'data': '', 'msg': f'上终止||{msg}'})

            if tools.get_price(dict_price=tools.get_price_dict(), contract_code=in_contract, price_type=in_end_up_price_type) >= float(in_value):
                return respond({'code': 1001, 'data': '', 'msg': f'上终止||上终止需大于当前{in_end_up_price_type}'})

        sql = "UPDATE information_client SET 上终止='%s',end_up_type='%s',end_up_price_type='%s' WHERE name = '%s' and contract='%s' " % (
            in_value, in_end_up_type, in_end_up_price_type, in_client_name, in_contract)
        tools.mysql_short_commit(sql)

    elif in_type == 'end_down':
        in_end_down_type = data_in['end_down_type']
        in_end_down_price_type = data_in['end_down_price_type']

        if in_end_down_type not in ['主动', '被动']:
            return respond({'code': 1001, 'data': '', 'msg': f'下终止||下终止执行类型不合法'})
        if in_end_down_price_type not in ['市价', '指数价', '标记价']:
            return respond({'code': 1001, 'data': '', 'msg': f'下终止||下终止价格类型不合法'})

        if in_value != 'None':
            type_check, msg, in_value = typecheck.is_posfloat(in_value, tools.get_contract_precision(in_contract))
            if not type_check:
                return respond({'code': 1001, 'data': '', 'msg': f'下终止||{msg}'})

            if tools.get_price(dict_price=tools.get_price_dict(), contract_code=in_contract, price_type=in_end_down_price_type) <= in_value:
                return respond({'code': 1001, 'data': '', 'msg': f'下终止需小于当前{in_end_down_price_type}'})

        sql = "UPDATE information_client SET 下终止='%s',end_down_type='%s',end_down_price_type='%s' WHERE name = '%s' and contract='%s'" % (
            in_value, in_end_down_type, in_end_down_price_type, in_client_name, in_contract)
        tools.mysql_short_commit(sql)

    elif in_type == 'end_time':
        in_end_time_type = data_in['end_time_type']

        if in_end_time_type not in ['主动', '被动']:
            return respond({'code': 1001, 'data': '', 'msg': f'止损时间||止损时间执行类型不合法'})

        if in_value != 'None':
            type_check, msg, in_value = typecheck.is_posint(in_value, border=False)
            if not type_check:
                return False, f'终止时间||格式不正确'

            in_value = int(in_value)/1000
            if int(in_value) < time.time():
                return respond({'code': 1001, 'data': '', 'msg': '止损时间||止损时间需大于当前时间'})

        sql = "UPDATE information_client SET 止损时间='%s',end_time_type='%s' WHERE name = '%s' and contract='%s' " % (
            in_value, in_end_time_type, in_client_name, in_contract)
        tools.mysql_short_commit(sql)

    return respond({'code': 1000, 'data': '', 'msg': '编辑成功'})


# 2.10 盈亏计算切换是否包含未启动
@app.route("/quant/trade/update_profit_loss_cal", methods=['POST'])
def quant_trade_update_profit_loss_cal():
    data_in = g.data_in

    temp_client_name = data_in['client_name']
    temp_contract_type = data_in['contract_code']
    temp_profit_loss_cal_status_unrun = str(data_in['profit_loss_cal_status_unrun'])  # 可选值True，False

    if temp_profit_loss_cal_status_unrun not in ['true', 'false']:
        return respond({'code': 1001, 'data': '', 'msg': '参数不合法'})

    if temp_profit_loss_cal_status_unrun == 'true':
        temp_profit_loss_cal_status_unrun = 'True'
    else:
        temp_profit_loss_cal_status_unrun = 'False'

    sql = "UPDATE information_client SET profit_loss_cal_status_unrun='%s' WHERE name = '%s' and contract='%s' " % (temp_profit_loss_cal_status_unrun, temp_client_name, temp_contract_type)
    tools.mysql_short_commit(sql)

    return respond({'code': 1000, 'data': '', 'msg': '修改成功'})


# 3.4平移接口
@app.route("/quant/trade/translation", methods=['POST'])
def quant_trade_translation():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_command = data_in['command']
    in_point = data_in['point'].replace('－', '-')
    in_translation_list = data_in['translation_list'].split(',')
    if '' in in_translation_list:
        in_translation_list.remove('')

    type_check, msg, in_point = typecheck.is_float(in_point, decimal_place=tools.get_contract_precision(in_contract))
    if not type_check:
        return {'code': 1001, 'data': '', 'msg': f'平移点数||{msg}'}

    if in_point == 0:
        return {'code': 1001, 'data': '', 'msg': f'平移点数||平移点数四舍五入后等于0'}

    will_translation_list = []
    if len(in_translation_list) == 0:
        if in_command == '全部平移':
            sql = "SELECT strategy_id FROM strategy_parameter_cycle_run WHERE client_name = '%s' and contract_type='%s' and strategy_status !='未启动' " % (in_client, in_contract)
        elif in_command == '多单平移':
            sql = "SELECT strategy_id FROM strategy_parameter_cycle_run WHERE client_name = '%s' and contract_type='%s' and strategy_status !='未启动' and direction = '多' " % (in_client, in_contract)
        elif in_command == '空单平移':
            sql = "SELECT strategy_id FROM strategy_parameter_cycle_run WHERE client_name = '%s' and contract_type='%s' and strategy_status !='未启动' and direction = '空' " % (in_client, in_contract)
        elif in_command == '多已持仓':
            sql = "SELECT strategy_id FROM strategy_parameter_cycle_run WHERE client_name = '%s' and contract_type='%s' and strategy_status !='未启动' and direction = '多' and (inposition+0)>0 " % (in_client, in_contract)
        elif in_command == '多未持仓':
            sql = "SELECT strategy_id FROM strategy_parameter_cycle_run WHERE client_name = '%s' and contract_type='%s' and strategy_status !='未启动' and direction = '多' and (inposition+0)=0 " % (in_client, in_contract)
        elif in_command == '空已持仓':
            sql = "SELECT strategy_id FROM strategy_parameter_cycle_run WHERE client_name = '%s' and contract_type='%s' and strategy_status !='未启动' and direction = '空' and (inposition+0)>0 " % (in_client, in_contract)
        elif in_command == '空未持仓':
            sql = "SELECT strategy_id FROM strategy_parameter_cycle_run WHERE client_name = '%s' and contract_type='%s' and strategy_status !='未启动' and direction = '空' and (inposition+0)=0 " % (in_client, in_contract)
        else:
            return respond({'code': 1001, 'data': '', 'msg': '批量指令非法'})

        results = tools.mysql_short_get(sql)
        for result in results:
            will_translation_list.append(result[0])
    else:
        will_translation_list = in_translation_list

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for strategy_id in will_translation_list:
        sql = "SELECT strategy_id,open,close,strategy_status,group_id FROM strategy_parameter_cycle_run WHERE strategy_id='%s' " % (strategy_id)
        results = tools.mysql_short_get(sql)

        open = results[0][1]
        close = results[0][2]
        strategy_status = results[0][3]
        group_id = results[0][4]

        open = round(float(open) + float(in_point), tools.get_contract_precision(in_contract))
        close = round(float(close) + float(in_point), tools.get_contract_precision(in_contract))

        if open < 0.1 ** tools.get_contract_precision(in_contract) or open > 100000000 or close < 0.1 ** tools.get_contract_precision(in_contract) or close > 100000000:
            msg = f'策略id:{strategy_id},预计平移后开:{open} 平:{close},开平非法本批次不执行'

            db.close()
            return respond({'code': 1001, 'data': '', 'msg': msg})

    for strategy_id in will_translation_list:
        sql = "UPDATE strategy_parameter_cycle_run SET strategy_status = '平移',points_translation='%s' WHERE strategy_id='%s' and strategy_status ='normal' " % (in_point, strategy_id)
        cursor.execute(sql)
        db.commit()

    db.close()

    return respond({'code': 1000, 'data': '', 'msg': '平移成功'})


# 3.6策略停止接口
@app.route("/quant/trade/stop", methods=['POST'])
def quant_trade_stop():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_command = data_in['command']
    in_stop_list = data_in['stop_list'].split(',')
    if '' in in_stop_list:
        in_stop_list.remove('')

    will_stop_list = []
    if len(in_stop_list) == 0:
        if in_command == '全部策略停止':
            sql = "SELECT strategy_id FROM strategy_parameter_cycle_run WHERE client_name = '%s' and contract_type='%s' and strategy_status !='未启动' " % (in_client, in_contract)
        elif in_command == '多单策略停止':
            sql = "SELECT strategy_id FROM strategy_parameter_cycle_run WHERE client_name = '%s' and contract_type='%s' and strategy_status !='未启动' and direction = '多' " % (in_client, in_contract)
        elif in_command == '空单策略停止':
            sql = "SELECT strategy_id FROM strategy_parameter_cycle_run WHERE client_name = '%s' and contract_type='%s' and strategy_status !='未启动' and direction = '空' " % (in_client, in_contract)
        else:
            return respond({'code': 1001, 'data': '', 'msg': '批量指令非法'})

        results = tools.mysql_short_get(sql)
        for result in results:
            will_stop_list.append(result[0])
    else:
        will_stop_list = in_stop_list

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for strategy_id in will_stop_list:
        # sql = "SELECT strategy_id,open,close,strategy_status,group_id FROM strategy_parameter_cycle_run WHERE strategy_id='%s' " % (strategy_id)
        # results = tools.mysql_short_get(sql)

        sql = "UPDATE strategy_parameter_cycle_run SET strategy_status = '策略停止' WHERE strategy_id='%s' and strategy_status ='normal' " % (strategy_id)
        cursor.execute(sql)
        db.commit()
    db.close()

    return respond({'code': 1000, 'data': '', 'msg': '停止成功'})


# 3.8平仓接口
@app.route("/quant/trade/end", methods=['POST'])
def quant_trade_end():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_command = data_in['command']
    in_maker_or_taker = data_in['maker_or_taker']
    in_end_list = data_in['end_list'].split(',')
    if '' in in_end_list:
        in_end_list.remove('')

    will_end_list = []
    if len(in_end_list) == 0:

        if in_command == '全部策略平仓':
            if in_maker_or_taker == '被动':
                sql = "UPDATE information_client SET account_status = '%s' WHERE name = '%s' and contract = '%s' " % ('终止被动', in_client, in_contract)
            else:
                sql = "UPDATE information_client SET account_status = '%s' WHERE name = '%s' and contract = '%s' " % ('终止', in_client, in_contract)
            tools.mysql_short_commit(sql)
            return respond({'code': 1000, 'data': '', 'msg': '平仓成功'})

        if in_command == '多单策略平仓':
            sql = "SELECT strategy_id FROM strategy_parameter_cycle_run WHERE client_name = '%s' and contract_type='%s' and strategy_status !='未启动' and direction = '多' " % (in_client, in_contract)
        elif in_command == '空单策略平仓':
            sql = "SELECT strategy_id FROM strategy_parameter_cycle_run WHERE client_name = '%s' and contract_type='%s' and strategy_status !='未启动' and direction = '空' " % (in_client, in_contract)
        else:
            return respond({'code': 1001, 'data': '', 'msg': '批量指令非法'})

        results = tools.mysql_short_get(sql)
        for result in results:
            will_end_list.append(result[0])
    else:
        will_end_list = in_end_list

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for strategy_id in will_end_list:
        sql = "UPDATE strategy_parameter_cycle_run SET strategy_status = '平仓',end_type = '%s' WHERE strategy_id='%s' " % (in_maker_or_taker, strategy_id)
        cursor.execute(sql)  # 执行SQL语句
        db.commit()
    db.close()

    return respond({'code': 1000, 'data': '', 'msg': '平仓成功'})


# 3.10同步委托
@app.route("/quant/trade/synchronous", methods=['POST'])
def quant_trade_synchronous():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']

    sql = "INSERT INTO  `orders_waiting`(`order_id`, `client`, `contract`, `strategy_id`, `direction`, `offset`, `price`, `volume`, `order_price_type`, `order_type`, `action`, `priority`, `timestamp` ) VALUES ('%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s')" % \
          ('--', in_client, in_contract, '--', '--', '--', '--', '--', '--', '同步委托', '同步数据', 3, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    tools.mysql_short_commit(sql)

    return respond({'code': 1000, 'data': '', 'msg': '同步委托数据'})


# 3.11批量修改策略参数  接口空值含义，不修改。止盈止损会传'None'
@app.route("/quant/trade/update_strategy_batch", methods=['POST'])
def quant_trade_update_strategy_batch():

    def convert_list_strategy_id_to_list():
        temp_list_strategy_id = eval(data_in['list_strategy_id'])

        temp_list = []
        if isinstance(temp_list_strategy_id, int):
            temp_list.append(temp_list_strategy_id)
        else:
            for temp_strategy_id in temp_list_strategy_id:
                temp_list.append(temp_strategy_id)

        return temp_list

    data_in = g.data_in

    temp_list_strategy_id = convert_list_strategy_id_to_list()
    temp_stop_loss = data_in['stop_loss']
    temp_stop_loss_type = data_in['stop_loss_type']
    temp_stop_loss_price_type = data_in['stop_loss_price_type']
    temp_stop_profit = data_in['stop_profit']
    temp_stop_profit_type = data_in['stop_profit_type']
    temp_stop_profit_price_type = data_in['stop_profit_price_type']
    temp_stop_amount_cycle = data_in['stop_amount_cycle']
    temp_stop_time_time_or_len = data_in['stop_time_time_or_len']
    temp_stop_time = data_in['stop_time']
    temp_stop_time_len = data_in['stop_time_len']
    temp_stop_time_type = data_in['stop_time_type']
    temp_group_id = data_in['group_id']

    sql = "SELECT contract_type FROM strategy_parameter_cycle_run where strategy_id = '%s' " % (temp_list_strategy_id[0])
    results = tools.mysql_short_get(sql)
    contract = results[0][0]

    # 开始进行组名合法性检查，组名中不能含有英文逗号
    if temp_group_id != '':
        type_check, msg, temp_group_id = typecheck.is_str(temp_group_id)
        if not type_check:
            return respond({'code': 1001, 'data': '', 'msg': f'组名||{msg}'})
        if '多' not in temp_group_id and '空' not in temp_group_id:
            return {'code': 1001, 'data': '', 'msg': '组名||组名中至少包含一个“多”或一个“空”字'}
        if '多' in temp_group_id and '空' in temp_group_id:
            return {'code': 1001, 'data': '', 'msg': '组名||组名中只能单独包含一个“多”或一个“空”字'}

    # 循环次数检查
    if temp_stop_amount_cycle != '':
        type_check, msg, temp_stop_amount_cycle = typecheck.is_posint(temp_stop_amount_cycle)
        if not type_check:
            return respond({'code': 1001, 'data': '', 'msg': f'循环次数||{msg}'})

    # 止损价格检查
    if temp_stop_loss != '' and temp_stop_loss != 'None':
        type_check, msg, temp_stop_loss = typecheck.is_posfloat(temp_stop_loss, decimal_place=tools.get_contract_precision(contract))
        if not type_check:
            return respond({'code': 1001, 'data': '', 'msg': f'止损价格||{msg}'})
    # 止盈价格检查
    if temp_stop_profit != '' and temp_stop_profit != 'None':
        type_check, msg, temp_stop_profit = typecheck.is_posfloat(temp_stop_profit, decimal_place=tools.get_contract_precision(contract))
        if not type_check:
            return respond({'code': 1001, 'data': '', 'msg': f'止盈价格||{msg}'})
    # 运行时长检查
    if temp_stop_time_len != '' and temp_stop_time_len != 'None':
        type_check, msg, temp_stop_time_len = typecheck.is_posfloat(temp_stop_time_len)
        if not type_check:
            return respond({'code': 1001, 'data': '', 'msg': f'运行时长||{msg}'})
    # 终止时间检查
    if temp_stop_time != '' and temp_stop_time != 'None':
        type_check, msg, temp_stop_time = typecheck.is_posint(temp_stop_time, border=False)
        if not type_check:
            return respond({'code': 1001, 'data': '', 'msg': f'终止时间||{msg}'})
        if temp_stop_time < time.time() * 1000:
            return {'code': 1001, 'data': '', 'msg': '终止时间||终止时间需大于当前时间'}

    # 先进行安全检查
    if len(temp_list_strategy_id) == 0:
        return respond({'code': 1001, 'data': '', 'msg': f'勾选||当前勾选列表为空'})
    else:
        # 获取最新价格
        dict_price = tools.get_price_dict()

        # 查策略信息
        db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
        cursor = db.cursor()

        for temp_strategy_id in temp_list_strategy_id:
            sql = "SELECT direction,amount_cycle,stop_loss,stop_loss_price_type,stop_profit,stop_profit_price_type,create_time,contract_type FROM strategy_parameter_cycle_run where strategy_id = '%s' " % (temp_strategy_id)
            cursor.execute(sql)  # 执行SQL语句
            results_strategy = cursor.fetchall()  # 获取所有记录列表

            direction = results_strategy[0][0]
            amount_cycle = results_strategy[0][1]
            stop_loss = results_strategy[0][2]
            stop_loss_price_type = results_strategy[0][3]
            stop_profit = results_strategy[0][4]
            stop_profit_price_type = results_strategy[0][5]
            create_time = results_strategy[0][6]
            contract_type = results_strategy[0][7]

            if temp_group_id != '':
                if direction not in temp_group_id:
                    return {'code': 1001, 'data': '', 'msg': '组名中的多空字样与策略方向不一致'}

            if temp_stop_amount_cycle != '':
                if temp_stop_amount_cycle <= float(amount_cycle):
                    return {'code': 1001, 'data': '', 'msg': '循环次数需大于当提前已循环次数'}

            if temp_stop_time_time_or_len != '':
                if temp_stop_time_time_or_len == 'None':
                    pass
                elif temp_stop_time_time_or_len == 'time':
                    pass
                elif temp_stop_time_time_or_len == 'len':
                    temp_temp_stop_time = int(temp_stop_time_len * 3600 + float(create_time))

                    if float(temp_temp_stop_time) < time.time():
                        return {'code': 1001, 'data': '', 'msg': '运行时长||运行时长需大于当前时间'}

            if temp_stop_loss != '' or temp_stop_loss_price_type != '' or temp_stop_profit != '' or temp_stop_profit_price_type != '':
                # 改止损
                if temp_stop_loss != '' and temp_stop_loss_price_type == '':
                    if temp_stop_loss == 'None':
                        pass
                    else:
                        if (direction == '多' and float(temp_stop_loss) >= tools.get_price(dict_price=dict_price, contract_code=contract_type, price_type=stop_loss_price_type)) or (direction == '空' and float(temp_stop_loss) <= tools.get_price(dict_price=dict_price, contract_code=contract_type, price_type=stop_loss_price_type)):
                            return {'code': 1001, 'data': '', 'msg': '止损价格不安全'}
                        else:
                            pass

                # 改止损价格类型
                if temp_stop_loss == '' and temp_stop_loss_price_type != '':
                    if stop_loss == 'None':
                        pass
                    else:
                        if (direction == '多' and float(stop_loss) >= tools.get_price(dict_price=dict_price, contract_code=contract_type, price_type=temp_stop_loss_price_type)) or (direction == '空' and float(stop_loss) <= tools.get_price(dict_price=dict_price, contract_code=contract_type, price_type=temp_stop_loss_price_type)):
                            return {'code': 1001, 'data': '', 'msg': '止损价格不安全'}
                        else:
                            pass

                # 改止损,改止损价格类型
                if temp_stop_loss != '' and temp_stop_loss_price_type != '':
                    if temp_stop_loss == 'None':
                        pass
                    else:
                        if (direction == '多' and float(temp_stop_loss) >= tools.get_price(dict_price=dict_price, contract_code=contract_type, price_type=temp_stop_loss_price_type)) or (direction == '空' and float(temp_stop_loss) <= tools.get_price(dict_price=dict_price, contract_code=contract_type, price_type=temp_stop_loss_price_type)):
                            return {'code': 1001, 'data': '', 'msg': '止损价格不安全'}
                        else:
                            pass

                # 改止盈
                if temp_stop_profit != '' and temp_stop_profit_price_type == '':

                    if temp_stop_profit == 'None':
                        pass
                    else:
                        if (direction == '多' and float(temp_stop_profit) <= tools.get_price(dict_price=dict_price, contract_code=contract_type, price_type=stop_profit_price_type)) or (direction == '空' and float(temp_stop_profit) >= tools.get_price(dict_price=dict_price, contract_code=contract_type, price_type=stop_profit_price_type)):
                            return {'code': 1001, 'data': '', 'msg': '止盈价格不安全'}
                        else:
                            pass

                # 改止盈价格类型
                if temp_stop_profit == '' and temp_stop_profit_price_type != '':
                    if stop_profit == 'None':
                        pass
                    else:
                        if (direction == '多' and float(stop_profit) <= tools.get_price(dict_price=dict_price, contract_code=contract_type, price_type=temp_stop_profit_price_type)) or (direction == '空' and float(stop_profit) >= tools.get_price(dict_price=dict_price, contract_code=contract_type, price_type=temp_stop_profit_price_type)):
                            return {'code': 1001, 'data': '', 'msg': '止盈价格不安全'}
                        else:
                            pass

                # 改止盈,改止盈价格类型
                if temp_stop_profit != '' and temp_stop_profit_price_type != '':
                    if temp_stop_profit == 'None':
                        pass
                    else:
                        if (direction == '多' and float(temp_stop_profit) <= tools.get_price(dict_price=dict_price, contract_code=contract_type, price_type=temp_stop_profit_price_type)) or (direction == '空' and float(temp_stop_profit) >= tools.get_price(dict_price=dict_price, contract_code=contract_type, price_type=temp_stop_profit_price_type)):
                            return {'code': 1001, 'data': '', 'msg': '止盈价格不安全'}
                        else:
                            pass

        db.close()

    # 开始执行编辑
    list_update_faild = []

    # 查策略信息
    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()

    for temp_strategy_id in temp_list_strategy_id:

        sql = "SELECT direction,amount_cycle,stop_loss,stop_loss_price_type,stop_profit,stop_profit_price_type,create_time,contract_type FROM strategy_parameter_cycle_run where strategy_id = '%s' " % (temp_strategy_id)
        cursor.execute(sql)  # 执行SQL语句
        results_strategy = cursor.fetchall()  # 获取所有记录列表

        direction = results_strategy[0][0]
        amount_cycle = results_strategy[0][1]
        stop_loss = results_strategy[0][2]
        stop_loss_price_type = results_strategy[0][3]
        stop_profit = results_strategy[0][4]
        stop_profit_price_type = results_strategy[0][5]
        create_time = results_strategy[0][6]
        contract_type = results_strategy[0][7]

        if temp_group_id != '':
            sql = "UPDATE strategy_parameter_cycle_run SET group_id='%s' WHERE strategy_id = '%s' " % (temp_group_id, temp_strategy_id)
            cursor.execute(sql)
            db.commit()

        if temp_stop_amount_cycle != '':
            sql = "UPDATE strategy_parameter_cycle_run SET stop_amount_cycle='%s' WHERE strategy_id = '%s'  " % (temp_stop_amount_cycle, temp_strategy_id)
            cursor.execute(sql)
            db.commit()

        if temp_stop_loss_type != '':
            sql = "UPDATE strategy_parameter_cycle_run SET stop_loss_type='%s' WHERE strategy_id = '%s' " % (temp_stop_loss_type, temp_strategy_id)
            cursor.execute(sql)
            db.commit()

        if temp_stop_profit_type != '':
            sql = "UPDATE strategy_parameter_cycle_run SET stop_profit_type='%s' WHERE strategy_id = '%s' " % (temp_stop_profit_type, temp_strategy_id)
            cursor.execute(sql)
            db.commit()

        if temp_stop_time_type != '':
            sql = "UPDATE strategy_parameter_cycle_run SET stop_time_type='%s' WHERE strategy_id = '%s' " % (temp_stop_time_type, temp_strategy_id)
            cursor.execute(sql)
            db.commit()

        if temp_stop_time_time_or_len != '':
            if temp_stop_time_time_or_len == 'None':
                temp_stop_time = 'None'
                temp_stop_time_len = 'None'

                sql = "UPDATE strategy_parameter_cycle_run SET stop_time_time_or_len='%s',stop_time='%s',stop_time_len='%s' WHERE strategy_id = '%s' " % (temp_stop_time_time_or_len, temp_stop_time, temp_stop_time_len, temp_strategy_id)
                cursor.execute(sql)  # 执行SQL语句
                db.commit()

            elif temp_stop_time_time_or_len == 'time':
                temp_temp_stop_time = str(float(temp_stop_time) / 1000)
                temp_stop_time_len = 'None'

                if float(temp_stop_time) > time.time():

                    sql = "UPDATE strategy_parameter_cycle_run SET stop_time_time_or_len='%s',stop_time='%s',stop_time_len='%s' WHERE strategy_id = '%s' " % (
                        temp_stop_time_time_or_len, temp_temp_stop_time, temp_stop_time_len, temp_strategy_id)
                    cursor.execute(sql)  # 执行SQL语句
                    db.commit()

                else:
                    # 不安全
                    list_update_faild.append(temp_strategy_id)

            elif temp_stop_time_time_or_len == 'len':
                temp_temp_stop_time = int(
                    float(temp_stop_time_len) * 3600 + float(create_time))

                if float(temp_temp_stop_time) > time.time():

                    sql = "UPDATE strategy_parameter_cycle_run SET stop_time_time_or_len='%s',stop_time='%s',stop_time_len='%s' WHERE strategy_id = '%s' " % (
                        temp_stop_time_time_or_len, temp_temp_stop_time, temp_stop_time_len, temp_strategy_id)
                    cursor.execute(sql)  # 执行SQL语句
                    db.commit()

                else:
                    # 不安全
                    list_update_faild.append(temp_strategy_id)

        if temp_stop_loss != '' or temp_stop_loss_price_type != '' or temp_stop_profit != '' or temp_stop_profit_price_type != '':
            # 获取最新价格
            dict_price = tools.get_price_dict()

            if temp_stop_loss != '' and temp_stop_loss_price_type == '':
                if temp_stop_loss == 'None':

                    sql = "UPDATE strategy_parameter_cycle_run SET stop_loss='%s' WHERE strategy_id = '%s' " % (
                        temp_stop_loss, temp_strategy_id)
                    cursor.execute(sql)  # 执行SQL语句
                    db.commit()
                else:
                    if direction == '多':
                        if float(temp_stop_loss) < tools.get_price(dict_price=dict_price,contract_code=contract_type,price_type=stop_loss_price_type):
                            # update

                            sql = "UPDATE strategy_parameter_cycle_run SET stop_loss='%s' WHERE strategy_id = '%s' " % (
                                temp_stop_loss, temp_strategy_id)
                            cursor.execute(sql)  # 执行SQL语句
                            db.commit()

                        else:
                            # 不安全
                            list_update_faild.append(temp_strategy_id)
                    elif direction == '空':
                        if float(temp_stop_loss) > tools.get_price(
                                dict_price=dict_price,
                                contract_code=contract_type,
                                price_type=stop_loss_price_type):
                            # update

                            sql = "UPDATE strategy_parameter_cycle_run SET stop_loss='%s' WHERE strategy_id = '%s' " % (
                                temp_stop_loss, temp_strategy_id)
                            cursor.execute(sql)  # 执行SQL语句
                            db.commit()

                        else:
                            # 不安全
                            list_update_faild.append(temp_strategy_id)

            if temp_stop_loss == '' and temp_stop_loss_price_type != '':
                if stop_loss == 'None':

                    sql = "UPDATE strategy_parameter_cycle_run SET stop_loss_price_type='%s' WHERE strategy_id = '%s' " % (
                        temp_stop_loss_price_type, temp_strategy_id)
                    cursor.execute(sql)  # 执行SQL语句
                    db.commit()
                else:
                    if direction == '多':
                        if float(stop_loss) < tools.get_price(
                                dict_price=dict_price,
                                contract_code=contract_type,
                                price_type=temp_stop_loss_price_type):
                            # update

                            sql = "UPDATE strategy_parameter_cycle_run SET stop_loss_price_type='%s' WHERE strategy_id = '%s' " % (
                                temp_stop_loss_price_type, temp_strategy_id)
                            cursor.execute(sql)  # 执行SQL语句
                            db.commit()
                            # db.close()
                        else:
                            # 不安全
                            list_update_faild.append(temp_strategy_id)
                    elif direction == '空':
                        if float(stop_loss) > tools.get_price(
                                dict_price=dict_price,
                                contract_code=contract_type,
                                price_type=temp_stop_loss_price_type):
                            # update

                            sql = "UPDATE strategy_parameter_cycle_run SET stop_loss_price_type='%s' WHERE strategy_id = '%s' " % (
                                temp_stop_loss_price_type, temp_strategy_id)
                            cursor.execute(sql)  # 执行SQL语句
                            db.commit()

                        else:
                            # 不安全
                            list_update_faild.append(temp_strategy_id)

            if temp_stop_loss != '' and temp_stop_loss_price_type != '':
                if temp_stop_loss == 'None':

                    sql = "UPDATE strategy_parameter_cycle_run SET stop_loss='%s',stop_loss_price_type='%s' WHERE strategy_id = '%s' " % (
                        temp_stop_loss, temp_stop_loss_price_type, temp_strategy_id)
                    cursor.execute(sql)  # 执行SQL语句
                    db.commit()
                else:
                    if direction == '多':
                        if float(temp_stop_loss) < tools.get_price(
                                dict_price=dict_price,
                                contract_code=contract_type,
                                price_type=temp_stop_loss_price_type):
                            # update

                            sql = "UPDATE strategy_parameter_cycle_run SET stop_loss='%s',stop_loss_price_type='%s' WHERE strategy_id = '%s' " % (
                                temp_stop_loss, temp_stop_loss_price_type, temp_strategy_id)
                            cursor.execute(sql)  # 执行SQL语句
                            db.commit()

                        else:
                            # 不安全
                            list_update_faild.append(temp_strategy_id)
                    elif direction == '空':
                        if float(temp_stop_loss) > tools.get_price(
                                dict_price=dict_price,
                                contract_code=contract_type,
                                price_type=temp_stop_loss_price_type):
                            # update

                            sql = "UPDATE strategy_parameter_cycle_run SET stop_loss='%s',stop_loss_price_type='%s' WHERE strategy_id = '%s' " % (
                                temp_stop_loss, temp_stop_loss_price_type, temp_strategy_id)
                            cursor.execute(sql)  # 执行SQL语句
                            db.commit()

                        else:
                            # 不安全
                            list_update_faild.append(temp_strategy_id)

            if temp_stop_profit != '' and temp_stop_profit_price_type == '':
                if temp_stop_profit == 'None':

                    sql = "UPDATE strategy_parameter_cycle_run SET stop_profit='%s' WHERE strategy_id = '%s' " % (
                        temp_stop_profit, temp_strategy_id)
                    cursor.execute(sql)  # 执行SQL语句
                    db.commit()
                else:
                    if direction == '多':
                        if float(temp_stop_profit) > tools.get_price(
                                dict_price=dict_price,
                                contract_code=contract_type,
                                price_type=stop_profit_price_type):
                            # update

                            sql = "UPDATE strategy_parameter_cycle_run SET stop_profit='%s' WHERE strategy_id = '%s' " % (
                                temp_stop_profit, temp_strategy_id)
                            cursor.execute(sql)  # 执行SQL语句
                            db.commit()

                        else:
                            # 不安全
                            list_update_faild.append(temp_strategy_id)
                    elif direction == '空':
                        if float(temp_stop_profit) < tools.get_price(
                                dict_price=dict_price,
                                contract_code=contract_type,
                                price_type=stop_profit_price_type):
                            # update

                            sql = "UPDATE strategy_parameter_cycle_run SET stop_profit='%s' WHERE strategy_id = '%s' " % (
                                temp_stop_profit, temp_strategy_id)
                            cursor.execute(sql)  # 执行SQL语句
                            db.commit()

                        else:
                            # 不安全
                            list_update_faild.append(temp_strategy_id)

            if temp_stop_profit == '' and temp_stop_profit_price_type != '':
                if stop_profit == 'None':

                    sql = "UPDATE strategy_parameter_cycle_run SET stop_profit_price_type='%s' WHERE strategy_id = '%s' " % (
                        temp_stop_profit_price_type, temp_strategy_id)
                    cursor.execute(sql)  # 执行SQL语句
                    db.commit()
                else:
                    if direction == '多':
                        if float(stop_profit) > tools.get_price(
                                dict_price=dict_price,
                                contract_code=contract_type,
                                price_type=temp_stop_profit_price_type):
                            # update

                            sql = "UPDATE strategy_parameter_cycle_run SET stop_profit_price_type='%s' WHERE strategy_id = '%s' " % (
                                temp_stop_profit_price_type, temp_strategy_id)
                            cursor.execute(sql)  # 执行SQL语句
                            db.commit()

                        else:
                            # 不安全
                            list_update_faild.append(temp_strategy_id)
                    elif direction == '空':
                        if float(stop_profit) < tools.get_price(
                                dict_price=dict_price,
                                contract_code=contract_type,
                                price_type=temp_stop_profit_price_type):
                            # update

                            sql = "UPDATE strategy_parameter_cycle_run SET stop_profit_price_type='%s' WHERE strategy_id = '%s' " % (
                                temp_stop_profit_price_type, temp_strategy_id)
                            cursor.execute(sql)  # 执行SQL语句
                            db.commit()

                        else:
                            # 不安全
                            list_update_faild.append(temp_strategy_id)

            if temp_stop_profit != '' and temp_stop_profit_price_type != '':
                if temp_stop_profit == 'None':

                    sql = "UPDATE strategy_parameter_cycle_run SET stop_profit='%s',stop_profit_price_type='%s' WHERE strategy_id = '%s' " % (
                        temp_stop_profit, temp_stop_profit_price_type, temp_strategy_id)
                    cursor.execute(sql)  # 执行SQL语句
                    db.commit()
                else:
                    if direction == '多':
                        if float(temp_stop_profit) > tools.get_price(
                                dict_price=dict_price,
                                contract_code=contract_type,
                                price_type=temp_stop_profit_price_type):
                            # update

                            sql = "UPDATE strategy_parameter_cycle_run SET stop_profit='%s',stop_profit_price_type='%s' WHERE strategy_id = '%s' " % (
                                temp_stop_profit, temp_stop_profit_price_type, temp_strategy_id)
                            cursor.execute(sql)  # 执行SQL语句
                            db.commit()

                        else:
                            # 不安全
                            list_update_faild.append(temp_strategy_id)
                    elif direction == '空':
                        if float(temp_stop_profit) < tools.get_price(
                                dict_price=dict_price,
                                contract_code=contract_type,
                                price_type=temp_stop_profit_price_type):
                            # update

                            sql = "UPDATE strategy_parameter_cycle_run SET stop_profit='%s',stop_profit_price_type='%s' WHERE strategy_id = '%s' " % (
                                temp_stop_profit, temp_stop_profit_price_type, temp_strategy_id)
                            cursor.execute(sql)  # 执行SQL语句
                            db.commit()

                        else:
                            # 不安全
                            list_update_faild.append(temp_strategy_id)

    db.close()

    len_list_update_faild = len(list(set(list_update_faild)))
    if len_list_update_faild == 0:
        return {'code': 1000, 'data': '', 'msg': '编辑成功'}
    else:
        return {'code': 1001, 'data': '', 'msg': '有' + str(len_list_update_faild) + '条策略不安全未完全修改,请核实修改结果'}


# 3.14 委托分布图_3
@app.route("/quant/trade/distribution_entrust_3", methods=['POST'])
def quant_trade_distribution_entrust_3():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']

    strategy_type = '循环策略'
    contract_type = in_contract
    client_name = in_client

    # 颜色
    # color = tools.distribution_config['distribution_entrust_barcolor_buy_open']['selected']
    # color2 = tools.distribution_config['distribution_entrust_barcolor_buy_open']['not_selected']

    sql = "SELECT * FROM strategy_parameter_cycle_run WHERE client_name='%s' and strategy_type='%s' and contract_type='%s' and strategy_status !='未启动' " % ( client_name, strategy_type, contract_type)
    results_strategy = tools.mysql_short_get(sql)

    # 获取当前客户非api订单信息
    sql = "SELECT * FROM orders_active WHERE client_name='%s' and order_source!='%s' and contract='%s' " % (client_name, 'api', contract_type)
    results_weborders = tools.mysql_short_get(sql)

    # 初始化标准数据集
    temp_datas = []

    # 处理策略订单
    for result in results_strategy:
        strategy_id = result[0]
        open = result[8]
        close = result[9]
        direction = result[10]
        inposition = float(result[11])
        volume = result[12]
        group_id = result[29]
        strategy_status = result[24]

        display = True
        for _ in ['_多被动', '_空被动', '_多主动', '_空主动']:
            if _ in group_id:
                display = False

        if not display:
            continue

        if inposition == 0:
            # print('这是开仓')
            # 构造数据中间体
            color_selected = tools.distribution_config['distribution_entrust_barcolor_buy_open'][ 'selected'] if direction == '多' else tools.distribution_config['distribution_entrust_barcolor_sell_open']['selected']
            color_not_selected = tools.distribution_config['distribution_entrust_barcolor_buy_open'][ 'not_selected'] if direction == '多' else tools.distribution_config['distribution_entrust_barcolor_sell_open']['not_selected']
            price = open
            volume = volume

            temp_dict = {
                'strategy_id': strategy_id,
                'price': float(price),
                'value': int(float(volume)),
                'group_id': group_id,
                'color_selected': color_selected,
                'color_not_selected': color_not_selected}

            temp_datas.append(temp_dict)

        elif inposition != 0:
            # print('这是平仓')
            # 构造数据中间体
            color_selected = tools.distribution_config['distribution_entrust_barcolor_sell_close']['selected'] if direction == '多' else tools.distribution_config['distribution_entrust_barcolor_buy_close']['selected']
            color_not_selected = tools.distribution_config['distribution_entrust_barcolor_sell_close']['not_selected'] if direction == '多' else tools.distribution_config['distribution_entrust_barcolor_buy_close']['not_selected']
            price = close
            volume = volume

            temp_dict = {
                'strategy_id': strategy_id,
                'price': float(price),
                'value': int(float(volume)),
                'group_id': group_id,
                'color_selected': color_selected,
                'color_not_selected': color_not_selected}

            temp_datas.append(temp_dict)

    for result in results_weborders:

        volume = result[7]
        trade_volume = result[8]
        price = result[9]
        direction = result[10]
        offset = result[11]

        strategy_id = 0
        volume = int(float(volume)) - int(float(trade_volume))
        group_id = 'web下单'

        if direction == 'buy' and offset == 'open':
            color_selected = tools.distribution_config['distribution_entrust_barcolor_buy_open']['selected']
            color_not_selected = tools.distribution_config['distribution_entrust_barcolor_buy_open']['not_selected']
        elif direction == 'sell' and offset == 'close':
            color_selected = tools.distribution_config['distribution_entrust_barcolor_sell_close']['selected']
            color_not_selected = tools.distribution_config['distribution_entrust_barcolor_sell_close']['not_selected']
        elif direction == 'sell' and offset == 'open':
            color_selected = tools.distribution_config['distribution_entrust_barcolor_sell_open']['selected']
            color_not_selected = tools.distribution_config['distribution_entrust_barcolor_sell_open']['not_selected']
        elif direction == 'buy' and offset == 'close':
            color_selected = tools.distribution_config['distribution_entrust_barcolor_buy_close']['selected']
            color_not_selected = tools.distribution_config['distribution_entrust_barcolor_buy_close']['not_selected']

        temp_dict = {
            'strategy_id': strategy_id,
            'price': float(price),
            'value': int(float(volume)),
            'group_id': group_id,
            'color_selected': color_selected,
            'color_not_selected': color_not_selected}
        temp_datas.append(temp_dict)

    temp_datas = sorted(temp_datas, key=lambda temp: temp['price'])

    if len(temp_datas) != 0:

        list_data_out = []
        length = len(temp_datas)

        i = 0
        while i < length:
            if i == 0 or i == length:
                list_data_out.append(temp_datas[i])
            else:
                list_data_out.append(temp_datas[i])

            i += 1

        return respond({'code': 1000, 'data': list_data_out, 'msg': '委托分布图刷新'})
    else:
        return respond({'code': 1000, 'data': [], 'msg': '没有数据'})


def dada_in_check_autostart3(check_type, data_in):

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_group_type = data_in['group_type']
    in_group_name = data_in['group_name']
    in_note = data_in['note']

    type_check, msg, in_note = typecheck.is_str(in_note)
    if not type_check:
        return False, f'备注||{msg}'

    list_in_group_type = ['策略分组', '自定义分组']
    if in_group_type not in list_in_group_type:
        return False, f'分组类型非法'

    if in_group_type == '策略分组':
        in_group_name2 = json.loads(copy.deepcopy(in_group_name))
        for in_group_name2_single in in_group_name2:
            if in_group_name2_single not in ['多单', '空单', '全部']:
                return False, f'策略分组组名不正确'

        if '全部' in in_group_name2:
            if '多单' in in_group_name2 or '空单' in in_group_name2:
                return False, f'分组非法'

        if '多单' in in_group_name2 and '空单' in in_group_name2:
            return False, f'分组非法'

    if check_type == '新增':
        in_run_type = data_in['run_type']

        if in_run_type not in ['草稿', '立即执行']:
            return False, f'运行方式非法'

    msg = ''
    return True, msg, data_in


# 2.20.1 启动3
@app.route("/quant/trade/get_autostart3", methods=['POST'])
def quant_trade_get_autostart3():
    def list_to_str(list):
        """
        用于列表转字符串
        :param list: 被传入的列表
        :return: 返回的逗号分割字符串
        """
        temp_str = ''
        for element_list in list:
            if temp_str == '':
                temp_str = str(element_list)
            else:
                temp_str = temp_str + ',' + str(element_list)
        return temp_str

    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']

    sql = "SELECT id,client,contract,group_type,group_name,status,execute_history,note FROM autostart3 where client='%s' and contract='%s' " % (in_client, in_contract)
    results = tools.mysql_short_get(sql)

    detail = []
    detail_draft = []
    for result in results:
        temp_dict = {}
        temp_dict['id'] = int(result[0])
        temp_dict['client'] = result[1]
        temp_dict['contract'] = result[2]
        temp_dict['group_type'] = result[3]
        temp_dict['group_name'] = list_to_str(json.loads(result[4]))
        temp_dict['group_name_object'] = json.loads(result[4])
        temp_dict['status'] = result[5]
        temp_dict['excute_history'] = result[6]
        temp_dict['note'] = result[7]

        temp_dict['_disabled'] = ''

        detail.append(temp_dict)

        if temp_dict['status'] == '草稿':
            detail_draft.append(temp_dict)

    data_out = {'code': 1000, 'data': {'detail': detail, 'detail_draft': detail_draft}, 'msg': '【启动】数据刷新'}
    return respond(data_out)


# 2.20.2新增某用户，某合约的启动3
@app.route("/quant/trade/insert_autostart3", methods=['POST'])
def quant_trade_insert_autostart3():
    data_in = g.data_in

    type_check, msg, data_in = dada_in_check_autostart3('新增', data_in)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'{msg}'})

    in_run_type = data_in['run_type']
    in_client = data_in['client']
    in_contract = data_in['contract']
    in_group_type = data_in['group_type']
    in_group_name = data_in['group_name']
    in_note = data_in['note']

    status = '草稿' if in_run_type == '草稿' else '立即执行'

    execute_history = f'{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())} [创建]初始状态为：{status}'

    sql = "INSERT INTO autostart3 (`client`, `contract`,  `group_type`, `group_name`, `status`, `note`,`execute_history` ) VALUES ('%s','%s','%s','%s','%s','%s','%s')" % (
        in_client, in_contract, in_group_type, in_group_name, status, in_note, execute_history)
    tools.mysql_short_commit(sql)

    data_out = {'code': 1000, 'data': '', 'msg': '【启动】保存成功'}
    return respond(data_out)


# 2.20.3修改某用户，某合约的启动3
@app.route("/quant/trade/update_autostart3", methods=['POST'])
def quant_trade_update_autostart3():
    data_in = g.data_in

    type_check, msg, data_in = dada_in_check_autostart3('编辑', data_in)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'{msg}'})

    in_id = data_in['id']
    in_client = data_in['client']
    in_contract = data_in['contract']
    in_group_type = data_in['group_type']
    in_group_name = data_in['group_name']
    in_note = data_in['note']

    sql = "update autostart3 set  `group_type`='%s', `group_name`='%s', `note`='%s' WHERE client = '%s' and contract = '%s' and id='%s' " % (
        in_group_type, in_group_name, in_note, in_client, in_contract, in_id)
    tools.mysql_short_commit(sql)

    data_out = {'code': 1000, 'data': '', 'msg': '【启动】编辑成功'}
    return respond(data_out)


# 2.20.4删除某用户，某合约的启动3（批量）
@app.route("/quant/trade/delete_autostart3_multi", methods=['POST'])
def quant_trade_delete_autostart3_multi():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_list_id = json.loads(data_in['list_id'])

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for id in in_list_id:
        sql = "DELETE FROM autostart3 WHERE client = '%s' and contract = '%s' and id='%s' " % (in_client, in_contract, id)
        cursor.execute(sql)
        db.commit()

    db.close()

    data_out = {'code': 1000, 'data': '', 'msg': '【启动】删除成功'}
    return respond(data_out)


# 2.20.4激活某用户，某合约的启动3（批量）
@app.route("/quant/trade/activate_autostart3_multi", methods=['POST'])
def quant_trade_activate_autostart3_multi():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_list_id = json.loads(data_in['list_id'])

    total_count = len(in_list_id)
    valid_count = 0

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for id in in_list_id:
        sql = "SELECT status FROM autostart3 where client='%s' and contract='%s' and id = '%s' " % (in_client, in_contract, id)  # SQL 查询语句
        cursor.execute(sql)
        results = cursor.fetchall()

        if results[0][0] == '草稿':
            sql = "update autostart3 set status = '立即执行' WHERE client = '%s' and contract = '%s' and id='%s' and status = '草稿' " % (in_client, in_contract, id)
            cursor.execute(sql)
            db.commit()

            execute_history = '\n' + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' ' + '[激活]' + g.device
            sql = "UPDATE autostart3 SET `execute_history` = CONCAT (`execute_history`,'%s') WHERE id = '%s' " % ( execute_history, id)
            cursor.execute(sql)
            db.commit()

            valid_count += 1

    db.close()

    if valid_count == total_count:
        data_out = {'code': 1000, 'data': '', 'msg': '【启动】选中运行成功'}
    elif valid_count == 0:
        data_out = {'code': 1001, 'data': '', 'msg': '【启动】选中运行失败'}
    else:
        data_out = {'code': 1000, 'data': '', 'msg': '【启动】选中运行部分成功'}

    return respond(data_out)


def dada_in_check_autoleave3(check_type, data_in):

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_group_type = data_in['group_type']
    in_group_name = data_in['group_name']
    in_position_type = data_in['position_type']
    in_excute_type = data_in['excute_type']
    in_excute_price = data_in['excute_price']
    in_excute_price_type = data_in['excute_price_type']
    in_excute_profit_or_loss_type = data_in['excute_profit_or_loss_type']
    in_note = data_in['note']

    type_check, msg, in_note = typecheck.is_str(in_note)
    if not type_check:
        return False, f'备注||{msg}', ''

    list_in_group_type = ['策略分组', '自定义分组']
    if in_group_type not in list_in_group_type:
        return False, f'分组类型非法', ''

    if in_group_type == '策略分组':
        in_group_name2 = json.loads(copy.deepcopy(in_group_name))
        for in_group_name2_single in in_group_name2:
            if in_group_name2_single not in ['多单', '空单', '全部']:
                return False, f'策略分组组名不正确', ''

        if '全部' in in_group_name2:
            if '多单' in in_group_name2 or '空单' in in_group_name2:
                return False, f'分组非法', ''

        if '多单' in in_group_name2 and '空单' in in_group_name2:
            return False, f'分组非法', ''

    if in_excute_type in ['设置止损', '设置止盈']:
        if in_excute_price_type not in ['市价', '指数价', '标记价']:
            return False, f'价格类型非法', ''
        if in_excute_profit_or_loss_type not in ['主动', '被动']:
            return False, f'执行类型非法', ''

        type_check, msg, in_excute_price = typecheck.is_posfloat(in_excute_price, tools.get_contract_precision(in_contract))
        if not type_check:
            return False, f'止盈止损价格||{msg}', ''

    if check_type == '新增':
        in_run_type = data_in['run_type']

        if in_run_type not in ['草稿', '立即执行']:
            return False, f'运行方式非法', ''

    msg = ''
    return True, msg, data_in

# 2.21.1 离场3
@app.route("/quant/trade/get_autoleave3", methods=['POST'])
def quant_trade_get_autoleave3():
    def list_to_str(list):
        """
        用于列表转字符串
        :param list: 被传入的列表
        :return: 返回的逗号分割字符串
        """
        temp_str = ''
        for element_list in list:
            if temp_str == '':
                temp_str = str(element_list)
            else:
                temp_str = temp_str + ',' + str(element_list)
        return temp_str

    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']

    sql = "SELECT id,client,contract,group_type,group_name,position_type,excute_type,excute_price,excute_price_type,excute_profit_or_loss_type,status,execute_history,note FROM autoleave3 where client='%s' and contract='%s' " % (
        in_client, in_contract)
    results = tools.mysql_short_get(sql)

    detail = []
    detail_draft = []

    for result in results:
        temp_dict = {}
        temp_dict['id'] = int(result[0])
        temp_dict['client'] = result[1]
        temp_dict['contract'] = result[2]
        temp_dict['group_type'] = result[3]
        temp_dict['group_name'] = list_to_str(json.loads(result[4]))
        temp_dict['group_name_object'] = json.loads(result[4])
        temp_dict['position_type'] = result[5]
        temp_dict['excute_type'] = result[6]
        if temp_dict['excute_type'] == '设置止损' or temp_dict['excute_type'] == '设置止盈':
            temp_dict['excute_price'] = result[7]
            temp_dict['excute_price_type'] = result[8]
            temp_dict['excute_price_display'] = temp_dict['excute_price'] + \
                '(' + temp_dict['excute_price_type'] + ')'
            temp_dict['excute_profit_or_loss_type'] = result[9]
        else:
            temp_dict['excute_price'] = '-'
            temp_dict['excute_price_type'] = '-'
            temp_dict['excute_price_display'] = '-'
            temp_dict['excute_profit_or_loss_type'] = '-'

        temp_dict['status'] = result[10]
        temp_dict['excute_history'] = result[11]
        temp_dict['note'] = result[12]

        temp_dict['_disabled'] = ''

        detail.append(temp_dict)

        if temp_dict['status'] == '草稿':
            detail_draft.append(temp_dict)

    data_out = {'code': 1000, 'data': {'detail': detail, 'detail_draft': detail_draft}, 'msg': '【离场】数据刷新'}
    return respond(data_out)


# 2.21.2新增某用户，某合约的离场3
@app.route("/quant/trade/insert_autoleave3", methods=['POST'])
def quant_trade_insert_autoleave3():
    data_in = g.data_in

    type_check, msg, data_in = dada_in_check_autoleave3('新增', data_in)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'{msg}'})

    in_run_type = data_in['run_type']
    in_client = data_in['client']
    in_contract = data_in['contract']
    in_group_type = data_in['group_type']
    in_group_name = data_in['group_name']
    in_position_type = data_in['position_type']
    in_excute_type = data_in['excute_type']
    in_excute_price = data_in['excute_price']
    in_excute_price_type = data_in['excute_price_type']
    in_excute_profit_or_loss_type = data_in['excute_profit_or_loss_type']
    in_note = data_in['note']


    if in_run_type == '草稿':
        status = '草稿'
    else:
        status = '立即执行'

    execute_history = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' ' + '[创建]初始状态为：' + status

    sql = "INSERT INTO autoleave3 (`client`, `contract`,  `group_type`, `group_name`,`position_type`,`excute_type`,`excute_price`,`excute_price_type`,`excute_profit_or_loss_type`, `status`, `note`,`execute_history` ) VALUES ('%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s')" % (
        in_client, in_contract, in_group_type, in_group_name, in_position_type, in_excute_type, in_excute_price, in_excute_price_type, in_excute_profit_or_loss_type, status, in_note, execute_history)
    tools.mysql_short_commit(sql)

    data_out = {'code': 1000, 'data': '', 'msg': '【离场】保存成功'}
    return respond(data_out)


# 2.21.3修改某用户，某合约的离场3
@app.route("/quant/trade/update_autoleave3", methods=['POST'])
def quant_trade_update_autoleave3():
    data_in = g.data_in

    type_check, msg, data_in = dada_in_check_autoleave3('编辑', data_in)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'{msg}'})

    in_id = data_in['id']
    in_client = data_in['client']
    in_contract = data_in['contract']
    in_group_type = data_in['group_type']
    in_group_name = data_in['group_name']
    in_position_type = data_in['position_type']
    in_excute_type = data_in['excute_type']
    in_excute_price = data_in['excute_price']
    in_excute_price_type = data_in['excute_price_type']
    in_excute_profit_or_loss_type = data_in['excute_profit_or_loss_type']
    in_note = data_in['note']

    sql = "update autoleave3 set  `group_type`='%s', `group_name`='%s', `position_type`='%s', `excute_type`='%s', `excute_price`='%s', `excute_price_type`='%s', `excute_profit_or_loss_type`='%s', `note`='%s' WHERE client = '%s' and contract = '%s' and id='%s' " % (
        in_group_type, in_group_name, in_position_type, in_excute_type, in_excute_price, in_excute_price_type, in_excute_profit_or_loss_type, in_note, in_client, in_contract, in_id)
    tools.mysql_short_commit(sql)

    data_out = {'code': 1000, 'data': '', 'msg': '【离场】编辑成功'}
    return respond(data_out)


# 2.21.4删除某用户，某合约的离场3（批量）
@app.route("/quant/trade/delete_autoleave3_multi", methods=['POST'])
def quant_trade_delete_autoleave3_multi():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_list_id = json.loads(data_in['list_id'])

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for id in in_list_id:
        sql = "DELETE FROM autoleave3 WHERE client = '%s' and contract = '%s' and id='%s' " % (
            in_client, in_contract, id)
        cursor.execute(sql)
        db.commit()

    db.close()

    data_out = {'code': 1000, 'data': '', 'msg': '【离场】删除成功'}
    return respond(data_out)


# 2.21.5激活某用户，某合约的离场3（批量）
@app.route("/quant/trade/activate_autoleave3_multi", methods=['POST'])
def quant_trade_activate_autoleave3_multi():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_list_id = json.loads(data_in['list_id'])

    total_count = len(in_list_id)
    valid_count = 0

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for id in in_list_id:
        sql = "SELECT status FROM autoleave3 where client='%s' and contract='%s' and id = '%s' " % (in_client, in_contract, id)  # SQL 查询语句
        cursor.execute(sql)
        results = cursor.fetchall()

        if results[0][0] == '草稿':
            sql = "update autoleave3 set status = '立即执行' WHERE client = '%s' and contract = '%s' and id='%s' and status = '草稿' " % (in_client, in_contract, id)
            cursor.execute(sql)
            db.commit()

            execute_history = '\n' + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' ' + '[激活]' + g.device
            sql = "UPDATE autoleave3 SET `execute_history` = CONCAT (`execute_history`,'%s') WHERE id = '%s' " % (execute_history, id)
            cursor.execute(sql)
            db.commit()

            valid_count += 1

    db.close()

    if valid_count == total_count:
        data_out = {'code': 1000, 'data': '', 'msg': '【离场】选中运行成功'}
    elif valid_count == 0:
        data_out = {'code': 1001, 'data': '', 'msg': '【离场】选中运行失败'}
    else:
        data_out = {'code': 1000, 'data': '', 'msg': '【离场】选中运行部分成功'}

    return respond(data_out)


def dada_in_check_autotranslation3(check_type, data_in):
    def str_to_list(str):
        """
        用于字符串转列表
        :param str: 被传入的逗号分割字符串
        :return: 返回的列表对象
        """
        list = json.loads(str)
        return list

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_translation_type = data_in['translation_type']
    in_price_direction = data_in['price_direction']
    in_price_type = data_in['price_type']
    in_price = data_in['price']
    in_translation_delta = data_in['translation_delta'].replace('－', '-')
    in_time_delta_count = data_in['time_delta_count']
    in_time_delta_unit = data_in['time_delta_unit']
    in_group_type = data_in['group_type']
    in_group_name = data_in['group_name']
    in_position_type = data_in['position_type']
    in_note = data_in['note']

    if check_type == '新增':
        in_batch_price_delta_type = data_in['batch_price_delta_type']
        in_batch_price_delta_value = data_in['batch_price_delta_value'].replace('－', '-')
        in_batch_translation_delta_type = data_in['batch_translation_delta_type']
        in_batch_translation_delta_value = data_in['batch_translation_delta_value'].replace('－', '-')
        in_batch_time_delta_count_type = data_in['batch_time_delta_count_type']
        in_batch_time_delta_count_value = data_in['batch_time_delta_count_value'].replace('－', '-')
        in_batch_count = data_in['batch_count']

        type_check, msg, data_in['batch_count'] = typecheck.is_posint(in_batch_count)
        if not type_check:
            return False, f'批量总数||{msg}', ''

        in_batch_type = '单个' if data_in['batch_count'] == 1 else '批量'

        # 检查批量参数
        if in_batch_type == '批量':
            type_check, msg, data_in['batch_price_delta_value'] = typecheck.is_float(in_batch_price_delta_value)
            if not type_check:
                return False, f'价格间隔||{msg}', ''

            type_check, msg, data_in['batch_translation_delta_value'] = typecheck.is_float(in_batch_translation_delta_value)
            if not type_check:
                return False, f'平移间隔||{msg}', ''

            type_check, msg, data_in['batch_time_delta_count_value'] = typecheck.is_float(in_batch_time_delta_count_value)
            if not type_check:
                return False, f'时间间隔||{msg}', ''

            type_check, msg, data_in['batch_count'] = typecheck.is_posint(in_batch_count)
            if not type_check:
                return False, f'批量总数||{msg}', ''

            # 检查价格参数
            if in_batch_price_delta_type == '数值':
                if float(in_price) + data_in['batch_price_delta_value'] * data_in['batch_count'] <= 0:
                    return False, f'价格批量参数会导致出发价格小于0', ''
            else:
                if float(in_price) * (1 + data_in['batch_price_delta_value'] / 100) * data_in['batch_count'] <= 0:
                    return False, f'价格批量参数会导致出发价格小于0', ''

            # 检查平移点数参数
            if in_translation_type == '触发价附近':
                if in_batch_translation_delta_type == '数值':
                    if float(in_translation_delta) + data_in['batch_translation_delta_value'] * data_in['batch_count'] <= 0:
                        return False, f'目标价差批量参数会导致平移点数小于0', ''
                else:
                    if float(in_translation_delta) * (1 + data_in['batch_translation_delta_value'] / 100) * data_in['batch_count'] <= 0:
                        return False, f'目标价差批量参数会导致平移点数小于0', ''

            # 检查时间参数
            if in_batch_time_delta_count_type == '数值':
                if float(in_time_delta_count) + data_in['batch_time_delta_count_value'] * data_in['batch_count'] <= 0:
                    return False, f'时间批量参数会导致出发价格小于0', ''
            else:
                if float(in_time_delta_count) * (1 + data_in['batch_time_delta_count_value'] / 100) * data_in['batch_count'] <= 0:
                    return False, f'时间批量参数会导致出发价格小于0', ''

    type_check, msg, data_in['note'] = typecheck.is_str(in_note)
    if not type_check:
        return False, f'备注||{msg}', ''

    # 1. 触发价格合法性判断
    type_check, msg, data_in['price'] = typecheck.is_posfloat(in_price, tools.get_contract_precision(in_contract))
    if not type_check:
        return False, f'触发价格||{msg}', ''

    # 2. 触发价格类型合法性判断
    list_price_type = ['市价', '指数价', '标记价']
    if in_price_type not in list_price_type:
        return False, f'触发价格类型非法', ''

    # 3. 平移方式检查
    list_in_translation_type = ['固定平移', '触发价附近']
    if in_translation_type not in list_in_translation_type:
        return False, f'平移方式非法', ''

    # 4. 平移点数,目标价差检查
    if in_translation_type == '固定平移':
        type_check, msg, data_in['translation_delta'] = typecheck.is_float(in_translation_delta, tools.get_contract_precision(in_contract))
        if not type_check:
            return False, f'平移点数||{msg}', ''
        if float(in_price) == 0:
            return False, f'平移点数||平移点数不能等于0', ''
    else:
        type_check, msg, data_in['translation_delta'] = typecheck.is_posfloat(in_translation_delta, tools.get_contract_precision(in_contract))
        if not type_check:
            return False, f'目标价差||{msg}', ''

    # 5. 等待时间检查
    type_check, msg, data_in['time_delta_count'] = typecheck.is_posfloat(in_time_delta_count)
    if not type_check:
        return False, f'等待时间||{msg}', ''

    # 计算in_point_translation_waiting_time
    if in_time_delta_unit not in ['秒', '分', '时', '天']:
        return False, f'等待时间单位||等待时间单位非法', ''

    # 6. 分组类型检查
    list_in_group_type = ['策略分组', '自定义分组']
    if in_group_type not in list_in_group_type:
        return False, f'分组类型||分组类型非法', ''

    # 7. 分组复选纠正
    # 开始检查分组信息
    group_list = str_to_list(in_group_name)
    if in_translation_type == '固定平移':
        if in_group_type == '策略分组':
            if '全部' in group_list and group_list != ['全部']:
                return False, f'策略分组||分组非法', ''
            if '多单' in group_list and '空单' in group_list:
                return False, f'策略分组||分组非法', ''
    elif in_translation_type == '触发价附近':
        if in_group_type == '策略分组':
            if '全部' in group_list:
                return False, f'分组||触发价附近不能选择策略分组全部', ''
            if '多单' in group_list and '空单' in group_list:
                return False, f'分组||触发价附近不能同时选择策略分组多单、空单', ''
        elif in_group_type == '自定义分组':
            for temp_temp_group_list in group_list:
                if '多' in temp_temp_group_list:
                    flag_temp_group_list_direction = '多'
                    break
                elif '空' in temp_temp_group_list:
                    flag_temp_group_list_direction = '空'
                    break
                else:
                    flag_temp_group_list_direction = '多'

            flag_group_list_remove = False
            group_list2 = copy.deepcopy(group_list)
            for temp_group_list in group_list2:
                if flag_temp_group_list_direction not in temp_group_list:
                    group_list.remove(temp_group_list)
                    flag_group_list_remove = True
            if flag_group_list_remove:
                return False, f'分组||触发价附近不能多空混选', ''

    # 分组判空
    if len(group_list) == 0:
        return False, f'分组||没有符合条件的分组', ''

    # 8. 触发价附近仅能匹配未持仓，纠正
    if in_translation_type == '触发价附近' and in_position_type != '未持仓':
        return False, f'持仓类型||持仓类型非法', ''

    if check_type == '新增':
        in_run_type = data_in['run_type']

        if in_run_type not in ['草稿', '立即执行']:
            return False, f'运行方式非法', ''

    return True, '', data_in


def create_autotranslation3(data_in):
    in_run_type = data_in['run_type']
    in_client = data_in['client']
    in_contract = data_in['contract']
    in_translation_type = data_in['translation_type']
    in_price_direction = data_in['price_direction']
    in_price_type = data_in['price_type']
    in_price = data_in['price']
    in_translation_delta = data_in['translation_delta']
    in_time_delta_count = data_in['time_delta_count']
    in_time_delta_unit = data_in['time_delta_unit']
    in_group_type = data_in['group_type']
    in_group_name = data_in['group_name']
    in_position_type = data_in['position_type']
    in_note = data_in['note']

    in_batch_price_delta_type = data_in['batch_price_delta_type']
    in_batch_price_delta_value = data_in['batch_price_delta_value']
    in_batch_translation_delta_type = data_in['batch_translation_delta_type']
    in_batch_translation_delta_value = data_in['batch_translation_delta_value']
    in_batch_time_delta_count_type = data_in['batch_time_delta_count_type']
    in_batch_time_delta_count_value = data_in['batch_time_delta_count_value']
    in_batch_count = data_in['batch_count']

    if in_batch_count == 1:
        in_batch_price_delta_value = 0
        in_batch_translation_delta_value = 0
        in_batch_time_delta_count_value = 0

    results = []
    while in_batch_count >= 1:

        insert = {}
        insert['in_client'] = in_client
        insert['in_contract'] = in_contract
        insert['in_translation_type'] = in_translation_type
        insert['in_price_direction'] = in_price_direction
        insert['in_price_type'] = in_price_type
        insert['in_price'] = in_price
        insert['in_translation_delta'] = in_translation_delta
        insert['in_time_delta_count'] = in_time_delta_count
        insert['in_time_delta_unit'] = in_time_delta_unit
        insert['in_group_type'] = in_group_type
        insert['in_group_name'] = in_group_name
        insert['in_position_type'] = in_position_type
        insert['in_note'] = in_note
        insert['status'] = '草稿' if in_run_type == '草稿' else '运行中'

        # 检查参数
        # 数值封顶 1000000
        if in_price <= 0 or in_price >= 1000000:
            return results
        if in_translation_delta <= -1000000 or in_translation_delta >= 1000000:
            return results
        if in_time_delta_count <= 0 or in_time_delta_count >= 1000000:
            return results

        results.append(insert)

        if in_batch_price_delta_type == '数值':
            in_price += in_batch_price_delta_value
        else:
            in_price *= (1 + in_batch_price_delta_value / 100)

        if in_batch_translation_delta_type == '数值':
            in_translation_delta += in_batch_translation_delta_value
        else:
            in_translation_delta *= (1 + in_batch_translation_delta_value / 100)

        if in_batch_time_delta_count_type == '数值':
            in_time_delta_count += in_batch_time_delta_count_value
        else:
            in_time_delta_count *= (1 + in_batch_time_delta_count_value / 100)

        # 四舍五入
        in_price = round(in_price, tools.get_contract_precision(in_contract))
        in_translation_delta = round(in_translation_delta, tools.get_contract_precision(in_contract))
        in_time_delta_count = round(in_time_delta_count, 4)

        # 修改批量参数
        in_batch_count -= 1

    return results

# 2.22.1 平移3
@app.route("/quant/trade/get_autotranslation3", methods=['POST'])
def quant_trade_get_autotranslation3():
    def list_to_str(list):
        """
        用于列表转字符串
        :param list: 被传入的列表
        :return: 返回的逗号分割字符串
        """
        temp_str = ''
        for element_list in list:
            if temp_str == '':
                temp_str = str(element_list)
            else:
                temp_str = temp_str + ',' + str(element_list)
        return temp_str

    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']

    sql = "SELECT id,client,contract,translation_type,price_direction,price_type,price,price_time,translation_delta,time_delta_count,time_delta_unit,group_type,group_name,position_type,status,execute_history,note FROM autotranslation3 where client='%s' and contract='%s' " % (
        in_client, in_contract)
    results = tools.mysql_short_get(sql)

    detail = []
    detail_draft = []
    for result in results:
        temp_dict = {}
        temp_dict['id'] = int(result[0])
        temp_dict['client'] = result[1]
        temp_dict['contract'] = result[2]
        temp_dict['translation_type'] = result[3]
        temp_dict['price_direction'] = result[4]
        temp_dict['price_direction_display'] = '(' + result[5] + ')' + result[4]
        temp_dict['price_type'] = result[5]
        temp_dict['price'] = float(result[6])
        if temp_dict['price'] == 0:
            temp_dict['price'] = ''
        temp_dict['translation_delta'] = result[8]
        temp_dict['translation_type_delta'] = temp_dict['translation_type'] + ':' + temp_dict['translation_delta']
        temp_dict['time_delta_count'] = result[9]
        temp_dict['time_delta_unit'] = result[10]
        temp_dict['time_delta_display'] = result[9] + result[10]
        temp_dict['group_type'] = result[11]
        temp_dict['group_name'] = list_to_str(json.loads(result[12]))
        temp_dict['group_name_object'] = json.loads(result[12])
        temp_dict['position_type'] = result[13]
        temp_dict['status'] = result[14]
        temp_dict['excute_history'] = result[15]
        temp_dict['note'] = result[16]

        temp_dict['_disabled'] = ''

        detail.append(temp_dict)
        if temp_dict['status'] == '草稿':
            detail_draft.append(temp_dict)

    # 详情排序
    detail = sorted(detail, key=lambda temp: float(temp['price']), reverse=True)

    data_out = {'code': 1000, 'data': {'detail': detail, 'detail_draft': detail_draft}, 'msg': '【平移】数据刷新'}
    return respond(data_out)


# 2.22.2新增某用户，某合约的平移3
@app.route("/quant/trade/insert_autotranslation3", methods=['POST'])
def quant_trade_insert_autotranslation3():
    data_in = g.data_in

    type_check, msg, data_in = dada_in_check_autotranslation3('新增', data_in)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'{msg}'})

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    for autotranslation3 in create_autotranslation3(data_in):

        in_client = autotranslation3['in_client']
        in_contract = autotranslation3['in_contract']
        in_translation_type = autotranslation3['in_translation_type']
        in_price_direction = autotranslation3['in_price_direction']
        in_price_type = autotranslation3['in_price_type']
        in_price = autotranslation3['in_price']
        in_translation_delta = autotranslation3['in_translation_delta']
        in_time_delta_count = autotranslation3['in_time_delta_count']
        in_time_delta_unit = autotranslation3['in_time_delta_unit']
        in_group_type = autotranslation3['in_group_type']
        in_group_name = autotranslation3['in_group_name']
        in_position_type = autotranslation3['in_position_type']
        status = autotranslation3['status']
        in_note = autotranslation3['in_note']

        execute_history = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' ' + '[创建]初始状态为：' + status

        sql = "INSERT INTO autotranslation3 (`client`, `contract`, `translation_type`, `price_direction`, `price_type`, `price`, `translation_delta`, `time_delta_count`, `time_delta_unit`, `group_type`, `group_name`, `position_type`, `status`, `note`,`execute_history`,`price_direction_condition1`,`price_direction_condition2`, `price_time` ) VALUES ('%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s')" % (
            in_client, in_contract, in_translation_type, in_price_direction, in_price_type, in_price, in_translation_delta, in_time_delta_count, in_time_delta_unit, in_group_type, in_group_name, in_position_type, status, in_note, execute_history, 'false', 'false', '0')
        tools.mysql_execute(db, sql)

    db.close()

    data_out = {'code': 1000, 'data': '', 'msg': '【平移】保存成功'}
    return respond(data_out)


# 2.22.3修改某用户，某合约的平移3
@app.route("/quant/trade/update_autotranslation3", methods=['POST'])
def quant_trade_update_autotranslation3():
    data_in = g.data_in

    type_check, msg, data_in = dada_in_check_autotranslation3('编辑', data_in)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'{msg}'})

    in_id = data_in['id']
    in_client = data_in['client']
    in_contract = data_in['contract']
    in_translation_type = data_in['translation_type']
    in_price_direction = data_in['price_direction']
    in_price_type = data_in['price_type']
    in_price = data_in['price']
    in_translation_delta = data_in['translation_delta']
    in_time_delta_count = data_in['time_delta_count']
    in_time_delta_unit = data_in['time_delta_unit']
    in_group_type = data_in['group_type']
    in_group_name = data_in['group_name']
    in_position_type = data_in['position_type']
    in_note = data_in['note']

    sql = "update autotranslation3 set `translation_type`='%s', `price_direction`='%s', `price_type`='%s', `price`='%s', `translation_delta`='%s', `time_delta_count`='%s', `time_delta_unit`='%s', `group_type`='%s', `group_name`='%s', `position_type`='%s', `note`='%s', `price_direction_condition1`='%s', `price_direction_condition2`='%s' WHERE client = '%s' and contract = '%s' and id='%s' " % (
        in_translation_type, in_price_direction, in_price_type, in_price, in_translation_delta, in_time_delta_count, in_time_delta_unit, in_group_type, in_group_name, in_position_type, in_note, 'false', 'false', in_client, in_contract, in_id)
    tools.mysql_short_commit(sql)

    data_out = {'code': 1000, 'data': '', 'msg': '【平移】编辑成功'}
    return respond(data_out)


# 2.22.4删除某用户，某合约的平移3（批量）
@app.route("/quant/trade/delete_autotranslation3_multi", methods=['POST'])
def quant_trade_delete_autotranslation3_multi():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_list_id = json.loads(data_in['list_id'])

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for id in in_list_id:
        sql = "DELETE FROM autotranslation3 WHERE client = '%s' and contract = '%s' and id='%s' " % (
            in_client, in_contract, id)
        cursor.execute(sql)
        db.commit()

    db.close()

    data_out = {'code': 1000, 'data': '', 'msg': '【平移】删除成功'}
    return respond(data_out)


# 2.22.5激活某用户，某合约的平移3（批量）
@app.route("/quant/trade/activate_autotranslation3_multi", methods=['POST'])
def quant_trade_activate_autotranslation3_multi():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_list_id = json.loads(data_in['list_id'])

    total_count = len(in_list_id)
    valid_count = 0

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for id in in_list_id:
        sql = "SELECT status FROM autotranslation3 where client='%s' and contract='%s' and id = '%s' " % (in_client, in_contract, id)  # SQL 查询语句
        cursor.execute(sql)
        results = cursor.fetchall()

        if results[0][0] == '草稿':
            sql = "update autotranslation3 set status = '运行中' WHERE client = '%s' and contract = '%s' and id='%s' and status = '草稿' " % (in_client, in_contract, id)
            cursor.execute(sql)
            db.commit()

            execute_history = '\n' + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' ' + '[激活]' + g.device
            sql = "UPDATE autotranslation3 SET `execute_history` = CONCAT (`execute_history`,'%s') WHERE id = '%s' " % (execute_history, id)
            cursor.execute(sql)
            db.commit()

            valid_count += 1

    db.close()

    if valid_count == total_count:
        data_out = {'code': 1000, 'data': '', 'msg': '【平移】选中运行成功'}
    elif valid_count == 0:
        data_out = {'code': 1001, 'data': '', 'msg': '【平移】选中运行失败'}
    else:
        data_out = {'code': 1000, 'data': '', 'msg': '【平移】选中运行部分成功'}

    return respond(data_out)


def dada_in_check_sprint3(check_type, data_in):

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_first_target_price_type = data_in['first_target_price_type']
    in_first_target_price = data_in['first_target_price']
    in_distance_interval_type = data_in['distance_interval_type']
    in_distance_interval = data_in['distance_interval']
    in_time_interval_count = data_in['time_interval_count']
    in_time_interval_unit = data_in['time_interval_unit']
    in_target_price_delta_type = data_in['target_price_delta_type']
    in_target_price_delta = data_in['target_price_delta']
    in_price_end = data_in['price_end']
    in_price_end_type = data_in['price_end_type']
    in_group_name = data_in['group_name']
    in_note = data_in['note']

    type_check, msg, data_in['note'] = typecheck.is_str(in_note)
    if not type_check:
        return False, f'备注||{msg}', ''

    # 1.冲刺方式检查
    if in_first_target_price_type not in ['上穿', '下刺', '实时价']:
        return False, f'执行方式||执行方式非法', ''

    # 2.若执行方式为 自定义
    if in_first_target_price_type in ['上穿', '下刺']:
        type_check, msg, data_in['first_target_price'] = typecheck.is_posfloat(in_first_target_price, tools.get_contract_precision(in_contract))
        if not type_check:
            return False, f'触发价格||{msg}', ''

    # 3. 检查距离间隔类型
    if in_distance_interval_type not in ['数值', '比例']:
        return False, f'距离间隔类型非法', ''

    # 5. 检查时间间隔数值
    type_check, msg, data_in['time_interval_count'] = typecheck.is_posfloat(in_time_interval_count)
    if not type_check:
        return False, f'时间间隔||{msg}', ''

    # 6. 检查时间间隔单位
    if in_time_interval_unit not in ['秒', '分', '时', '天']:
        return False, f'时间间隔单位非法', ''

    # 7. 检查目标价差类型
    if in_target_price_delta_type not in ['数值', '比例']:
        return False, f'目标价差类型非法', ''

    # 检查距离间隔类型与目标价差间隔类型是否一致
    if in_distance_interval_type != in_target_price_delta_type:
        return False, f'距离间隔类型与目标价差间隔类型必须一致', ''

    # 8. 检查目标价差
    type_check, msg, data_in['target_price_delta'] = typecheck.is_posfloat(in_target_price_delta, tools.get_contract_precision(in_contract))
    if not type_check:
        return False, f'目标价差||{msg}', ''

    # 9. 检查终止价格类型
    if in_price_end_type not in ['市价', '指数价', '标记价']:
        return False, f'终止价格类型非法', ''

    # 10. 检查终止价格
    type_check, msg, data_in['price_end'] = typecheck.is_posfloat(in_price_end, tools.get_contract_precision(in_contract))
    if not type_check:
        return False, f'终止价格||{msg}', ''

    # 11. 检查距离间隔与目标价差关系,若 距离间隔<目标价差非法
    if float(in_distance_interval) <= float(in_target_price_delta):
        return False, f'距离间隔需大于目标价差', ''

    # 检查冲刺分组
    in_group_name2 = json.loads(in_group_name)
    direction = []
    for in_group_name2_single in in_group_name2:
        if '多' in in_group_name2_single and '多' not in direction:
            direction.append('多')
        if '空' in in_group_name2_single and '空' not in direction:
            direction.append('空')
    if len(direction) > 1 or len(in_group_name2) == 0:
        return False, f'冲刺分组非法', ''

    # 判断当前分组方向
    group_name_direction = '多' if '多' in in_group_name else '空'

    # 检查组方向与首次目标价格类型的关系
    if in_first_target_price_type == '上穿' and group_name_direction == '空':
        return False, f'上穿不能选择空方向分组', ''
    if in_first_target_price_type == '下刺' and group_name_direction == '多':
        return False, f'下刺不能选择多方向策略', ''

    if check_type == '新增':
        in_run_type = data_in['run_type']

        if in_run_type not in ['草稿', '立即执行']:
            return False, f'运行方式非法', ''

    msg = ''
    return True, msg, data_in

# 2.23.1 冲刺3
@app.route("/quant/trade/get_sprint3", methods=['POST'])
def quant_trade_get_sprint3():
    def list_to_str(list):
        """
        用于列表转字符串
        :param list: 被传入的列表
        :return: 返回的逗号分割字符串
        """
        temp_str = ''
        for element_list in list:
            if temp_str == '':
                temp_str = str(element_list)
            else:
                temp_str = temp_str + ',' + str(element_list)
        return temp_str

    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']

    sql = "SELECT id,client,contract,first_target_price_type,first_target_price,distance_interval_type,distance_interval,time_interval_count,time_interval_unit,target_price_delta_type,target_price_delta,price_end_type,price_end,group_name,status,execute_history,note FROM autosprint3 where client='%s' and contract='%s' " % (
        in_client, in_contract)
    results = tools.mysql_short_get(sql)

    detail = []
    detail_draft = []

    for result in results:
        temp_dict = {}
        temp_dict['id'] = int(result[0])
        temp_dict['client'] = result[1]
        temp_dict['contract'] = result[2]
        temp_dict['first_target_price_type'] = result[3]
        temp_dict['first_target_price'] = result[4]
        temp_dict['first_target_price_display'] = temp_dict['first_target_price_type'] + ':' + temp_dict['first_target_price'] + \
            '(市价)' if temp_dict['first_target_price_type'] in ['上穿', '下刺'] else temp_dict['first_target_price_type']
        temp_dict['distance_interval_type'] = result[5]
        temp_dict['distance_interval'] = result[6]
        temp_dict['distance_interval_display'] = temp_dict['distance_interval_type'] + \
            ':' + temp_dict['distance_interval']
        temp_dict['time_interval_count'] = result[7]
        temp_dict['time_interval_unit'] = result[8]
        temp_dict['time_interval_display'] = temp_dict['time_interval_count'] + \
            temp_dict['time_interval_unit']
        temp_dict['target_price_delta_type'] = result[9]
        temp_dict['target_price_delta'] = result[10]
        temp_dict['target_price_delta_display'] = temp_dict['target_price_delta_type'] + \
            ':' + temp_dict['target_price_delta']
        temp_dict['price_end_type'] = result[11]
        temp_dict['price_end'] = result[12]
        temp_dict['price_end_display'] = temp_dict['price_end'] + \
            '(' + temp_dict['price_end_type'] + ')'
        temp_dict['group_name'] = list_to_str(json.loads(result[13]))
        temp_dict['group_name_object'] = json.loads(result[13])
        temp_dict['status'] = result[14]
        temp_dict['excute_history'] = result[15]
        temp_dict['note'] = result[16]

        temp_dict['_disabled'] = ''

        detail.append(temp_dict)

        if temp_dict['status'] == '草稿':
            detail_draft.append(temp_dict)

    data_out = {'code': 1000, 'data': {'detail': detail, 'detail_draft': detail_draft}, 'msg': '【冲刺】数据刷新'}
    return respond(data_out)


# 2.23.2新增某用户，某合约的冲刺3
@app.route("/quant/trade/insert_sprint3", methods=['POST'])
def quant_trade_insert_sprint3():
    data_in = g.data_in

    type_check, msg, data_in = dada_in_check_sprint3('新增', data_in)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'{msg}'})

    in_run_type = data_in['run_type']
    in_client = data_in['client']
    in_contract = data_in['contract']
    in_first_target_price_type = data_in['first_target_price_type']
    in_first_target_price = data_in['first_target_price']
    in_distance_interval_type = data_in['distance_interval_type']
    in_distance_interval = data_in['distance_interval']
    in_time_interval_count = data_in['time_interval_count']
    in_time_interval_unit = data_in['time_interval_unit']
    in_target_price_delta_type = data_in['target_price_delta_type']
    in_target_price_delta = data_in['target_price_delta']
    in_price_end = data_in['price_end']
    in_price_end_type = data_in['price_end_type']
    in_group_name = data_in['group_name']
    in_note = data_in['note']

    if in_run_type == '草稿':
        status = '草稿'
    else:
        status = '运行中'

    execute_history = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' ' + '[创建]初始状态为：' + status

    sql = "INSERT INTO autosprint3 (`client`, `contract`, `first_target_price_type`, `first_target_price`, `distance_interval`, `distance_interval_type`, `time_interval_count`, `time_interval_unit`, `target_price_delta_type`, `target_price_delta`, `price_end`, `price_end_type`,`group_name`, `status`, `note`,`execute_history`, `price_direction_condition1`, `price_direction_condition2` ) VALUES ('%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s')" % (
        in_client, in_contract, in_first_target_price_type, in_first_target_price, in_distance_interval, in_distance_interval_type, in_time_interval_count, in_time_interval_unit, in_target_price_delta_type, in_target_price_delta, in_price_end, in_price_end_type, in_group_name, status, in_note, execute_history, 'false', 'false')
    tools.mysql_short_commit(sql)

    data_out = {'code': 1000, 'data': '', 'msg': '【冲刺】保存成功'}
    return respond(data_out)


# 2.23.3修改某用户，某合约的冲刺3
@app.route("/quant/trade/update_sprint3", methods=['POST'])
def quant_trade_update_sprint3():
    data_in = g.data_in

    type_check, msg, data_in = dada_in_check_sprint3('编辑', data_in)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'{msg}'})

    in_id = data_in['id']
    in_client = data_in['client']
    in_contract = data_in['contract']
    in_first_target_price_type = data_in['first_target_price_type']
    in_first_target_price = data_in['first_target_price']
    in_distance_interval = data_in['distance_interval']
    in_distance_interval_type = data_in['distance_interval_type']
    in_time_interval_count = data_in['time_interval_count']
    in_time_interval_unit = data_in['time_interval_unit']
    in_target_price_delta_type = data_in['target_price_delta_type']
    in_target_price_delta = data_in['target_price_delta']
    in_price_end = data_in['price_end']
    in_price_end_type = data_in['price_end_type']
    in_group_name = data_in['group_name']
    in_note = data_in['note']

    # 获取旧数据
    sql = "SELECT distance_interval_type,distance_interval,time_interval_count,time_interval_unit,price_end_type,price_end,status,group_name FROM autosprint3 where client='%s' and contract='%s' and id='%s' " % (
        in_client, in_contract, in_id)
    results = tools.mysql_short_get(sql)

    old_distance_interval_type = results[0][0]
    old_distance_interval = results[0][1]
    old_time_interval_count = results[0][2]
    old_time_interval_unit = results[0][3]
    old_price_end_type = results[0][4]
    old_price_end = results[0][5]
    old_status = results[0][6]
    old_group_name = results[0][7]

    # 判断当前分组方向
    group_name_direction = '多' if '多' in old_group_name else '空'
    group_name_direction_new = '多' if '多' in in_group_name else '空'

    if group_name_direction != group_name_direction_new:
        data_out = {'code': 1001, 'data': '', 'msg': '编辑前后分组方向不一致'}
        return respond(data_out)

    # 检查组方向与首次目标价格类型的关系
    if in_first_target_price_type == '上穿' and group_name_direction == '空':
        data_out = {'code': 1001, 'data': '', 'msg': '上穿不能选择空方向分组'}
        return respond(data_out)
    if in_first_target_price_type == '下刺' and group_name_direction == '多':
        data_out = {'code': 1001, 'data': '', 'msg': '下刺不能选择多方向策略'}
        return respond(data_out)

    # 判断终止价格合法性
    if old_status != '草稿':
        if group_name_direction == '多' and in_price_end < tools.get_price(dict_price=tools.get_price_dict(), contract_code=in_contract, price_type=in_price_end_type):
            data_out = {'code': 1001, 'data': '', 'msg': '终止价格非法'}
            return respond(data_out)
        if group_name_direction == '空' and in_price_end > tools.get_price(dict_price=tools.get_price_dict(), contract_code=in_contract, price_type=in_price_end_type):
            data_out = {'code': 1001, 'data': '', 'msg': '终止价格非法'}
            return respond(data_out)

    reset_distance_interval = False
    reset_time_interval = False

    if old_status == '冲刺中':
        # 检查距离间隔是否一致
        if old_distance_interval_type != in_distance_interval_type or old_distance_interval != in_distance_interval:
            # 需要距离复位
            reset_distance_interval = True

        # 检查时间是否一致
        def get_time_second(time_unit, time_length):
            if time_unit == '秒':
                time_delta = float(time_length) * 1
            elif time_unit == '分':
                time_delta = float(time_length) * 1 * 60
            elif time_unit == '时':
                time_delta = float(time_length) * 1 * 60 * 60
            elif time_unit == '天':
                time_delta = float(time_length) * 1 * 60 * 60 * 24
            else:
                time_delta = 0
        if get_time_second(old_time_interval_unit, old_time_interval_count) != get_time_second(in_time_interval_unit, in_time_interval_count):
            # 需要时间复位
            reset_time_interval = True

    sql_part1 = "update autosprint3 set `first_target_price_type`='%s', `first_target_price`='%s', `distance_interval`='%s', `distance_interval_type`='%s', `time_interval_count`='%s', `time_interval_unit`='%s', `target_price_delta_type`='%s', `target_price_delta`='%s', `price_end`='%s', `price_end_type`='%s',`group_name`='%s', `note`='%s', `price_direction_condition1`='%s', `price_direction_condition2`='%s' " % (
        in_first_target_price_type, in_first_target_price, in_distance_interval, in_distance_interval_type, in_time_interval_count, in_time_interval_unit, in_target_price_delta_type, in_target_price_delta, in_price_end, in_price_end_type, in_group_name, in_note, 'false', 'false')
    sql_part2 = ''
    sql_part3 = ''
    sql_part4 = "WHERE client = '%s' and contract = '%s' and id='%s' " % (in_client, in_contract, in_id)

    if reset_distance_interval:
        sql_part2 = ", `last_target_price`='%s' " % (tools.get_price(dict_price=tools.get_price_dict(), contract_code=in_contract, price_type='市价'))

    if reset_time_interval:
        sql_part3 = ", `last_sprint_time`='%s' " % (time.time())

    sql = sql_part1 + sql_part2 + sql_part3 + sql_part4
    tools.mysql_short_commit(sql)

    data_out = {'code': 1000, 'data': '', 'msg': '【冲刺】编辑成功'}
    return respond(data_out)


# 2.23.4删除某用户，某合约的冲刺3（批量）
@app.route("/quant/trade/delete_sprint3_multi", methods=['POST'])
def quant_trade_delete_sprint3_multi():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_list_id = json.loads(data_in['list_id'])

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for id in in_list_id:
        sql = "DELETE FROM autosprint3 WHERE client = '%s' and contract = '%s' and id='%s' " % (
            in_client, in_contract, id)
        cursor.execute(sql)
        db.commit()

    db.close()

    data_out = {'code': 1000, 'data': '', 'msg': '【冲刺】删除成功'}
    return respond(data_out)


# 2.23.5激活某用户，某合约的冲刺3（批量）
@app.route("/quant/trade/activate_sprint3_multi", methods=['POST'])
def quant_trade_activate_sprint3_multi():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_list_id = json.loads(data_in['list_id'])

    total_count = len(in_list_id)
    valid_count = 0

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for id in in_list_id:
        sql = "SELECT status FROM autosprint3 where client='%s' and contract='%s' and id = '%s' " % (in_client, in_contract, id)  # SQL 查询语句
        cursor.execute(sql)
        results = cursor.fetchall()

        if results[0][0] == '草稿':
            sql = "update autosprint3 set status = '运行中' WHERE client = '%s' and contract = '%s' and id='%s' and status = '草稿'  " % (in_client, in_contract, id)
            cursor.execute(sql)
            db.commit()

            execute_history = '\n' +  time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' ' + '[激活]' + g.device
            sql = "UPDATE autosprint3 SET `execute_history` = CONCAT (`execute_history`,'%s') WHERE id = '%s' " % (execute_history, id)
            cursor.execute(sql)
            db.commit()

            valid_count += 1

    db.close()

    if valid_count == total_count:
        data_out = {'code': 1000, 'data': '', 'msg': '【冲刺】选中运行成功'}
    elif valid_count == 0:
        data_out = {'code': 1001, 'data': '', 'msg': '【冲刺】选中运行失败'}
    else:
        data_out = {'code': 1000, 'data': '', 'msg': '【冲刺】选中运行部分成功'}

    return respond(data_out)


# 自动执行合法性检查
def legality_check(data,client, contract):
    def character_legality_check(element):
        try:
            element_type = element['type']
            element_name = element['name']

            if element_name == '有效时间区间':
                time_start = element['time'][0]
                time_end = element['time'][1]

                try:
                    timestamp_start = time.mktime(time.strptime(
                        time_start, "%Y-%m-%dT%H:%M:%S.%fZ")) + 8 * 3600
                    timestamp_end = time.mktime(time.strptime(
                        time_end, "%Y-%m-%dT%H:%M:%S.%fZ")) + 8 * 3600

                    if timestamp_end <= time.time():
                        return [False, '时间区间右侧时间需大于当前时间']
                    if timestamp_end <= timestamp_start:
                        return [False, '时间区间右侧时间需大于左侧时间']
                except BaseException:
                    return [False, '时间区间不能为非法字符']

            elif element_name == '时刻':
                timestamp = element['timestamp']

                try:
                    time_length = float(timestamp)
                    if time_length <= time.time() * 1000:
                        return [False, '时刻需大于当前时间']
                except BaseException:
                    return [False, '时刻不能为非法字符']

            elif element_name == '时间':
                time_type = element['time_type']  # [内,后]
                if time_type not in ['内', '后']:
                    return [False, '时长方向错误']
                time_unit = element['time_unit']  # [秒,分,时,天]
                if time_unit not in ['秒', '分', '时', '天']:
                    return [False, '时长单位错误']
                time_length = element['time_length']  # 数值

                type_check, msg, time_length = typecheck.is_posfloat(time_length)
                if not type_check:
                    return [False, f'时长||{msg}']

            elif element_name == '价格':
                price_type = element['price_type']  # [市价,指数价,标记价]
                if price_type not in ['市价', '指数价', '标记价']:
                    return [False, '价格类型不存在']
                # [上穿,下刺,未上穿,未下刺,大于,小于]
                price_direction = element['price_direction']
                if price_direction not in ['上穿', '下刺', '未上穿', '未下刺', '大于', '小于']:
                    return [False, '价格元素方向不存在']

                type_check, msg, element['price'] = typecheck.is_posfloat(element['price'],decimal_place=tools.get_contract_precision(contract))
                if not type_check:
                    return [False, f'价格||{msg}']

            elif element_name == '净值':
                # [上穿,下刺,未上穿,未下刺,大于,小于]
                networth_direction = element['networth_direction']
                if networth_direction not in ['上穿', '下刺', '未上穿', '未下刺', '大于', '小于']:
                    return [False, '净值元素方向不存在']

                type_check, msg, element['networth'] = typecheck.is_posfloat(element['networth'])
                if not type_check:
                    return [False, f'净值||{msg}']

            elif element_name == '逻辑运算':
                logical_operator = element['logical_operator']  # 逻辑运算关系
                if logical_operator not in ['且', '或']:
                    return [False, '逻辑元素非法']

            elif element_name == '启动':
                if 'note' not in element:
                    return [False, '动作元素没有备注']
                if element['note'] == '':
                    return [False, '动作元素没有备注']

            elif element_name == '平移':
                if 'note' not in element:
                    return [False, '动作元素没有备注']
                if element['note'] == '':
                    return [False, '动作元素没有备注']

            elif element_name == '冲刺':
                if 'note' not in element:
                    return [False, '动作元素没有备注']
                if element['note'] == '':
                    return [False, '动作元素没有备注']

            elif element_name == '离场':
                if 'note' not in element:
                    return [False, '动作元素没有备注']
                if element['note'] == '':
                    return [False, '动作元素没有备注']

            else:
                return [False, '元素不存在']
            return [True, '']
        except BaseException:
            return [False, '元素检查失败']

    try:
        line_index = 0
        for command_index in range(len(data)):  # command_index 为第2级索引
            # print('---------------')
            # print(f'第{command_index+1}个指令：',data[command_index])
            command_status = data[command_index]['status']
            element_list = data[command_index]['data']
            command_type = data[command_index]['type']
            if command_type == '条件':
                line_index += 1

            # 构建元素列表
            element_items = []
            for element_index in range(len(element_list)):  # element_index 为第3级索引
                # print(f'第{command_index+1}个指令-第{element_index+1}个元素：',data[command_index]['data'][element_index])
                # print('element_list',element_list)
                element = element_list[element_index]
                element_type = element['type']
                element_name = element['name']

                if element_name == '有效时间区间':
                    element_items.append(element_name)

                elif element_name == '时间':
                    time_type = element['time_type']  # [内,后]
                    element_items.append(element_name + time_type)

                elif element_name == '价格':
                    # [上穿,下刺,未上穿,未下刺,大于,小于]
                    price_direction = element['price_direction']
                    element_items.append(price_direction)

                elif element_name == '净值':
                    # [上穿,下刺,未上穿,未下刺,大于,小于]
                    networth_direction = element['networth_direction']
                    element_items.append(networth_direction)

                elif element_name == '逻辑运算':
                    logical_operator = element['logical_operator']  # 逻辑运算关系
                    element_items.append(logical_operator)

            # print(element_items)
            # time.sleep(0.1)

            # 判断“未上传”/“未下刺”是否需要降级
            not_pierced_downgrade = False
            if '上穿' in element_items or '下刺' in element_items:
                not_pierced_downgrade = True
                # print('降级')

            # 统计一个指令中各个条件类型元素数量
            element_abstract = {
                # 维度1
                '总数': 0,

                # 维度2
                '有限时间': 0,
                '无限时间': 0,
                '短元素': 0,
                '长元素': 0,
                '瞬间元素': 0,
                '状态元素': 0,
                '逻辑元素': 0,

                # 维度3
                '时间元素总数': 0,
                '状态元素总数': 0,
                '条件元素总数': 0,

                # 维度4
                '时间区间': 0,
                '时间': {
                    '内': 0,
                    '后': 0
                },
                '时刻': 0,
                '价格': {
                    '上穿': 0,
                    '下刺': 0,
                    '未上穿': 0,
                    '未下刺': 0,
                    '大于': 0,
                    '小于': 0
                },
                '净值': {
                    '上穿': 0,
                    '下刺': 0,
                    '未上穿': 0,
                    '未下刺': 0,
                    '大于': 0,
                    '小于': 0
                },
                '逻辑运算': {
                    '且': 0,
                    '或': 0
                }
            }

            for element_index in range(len(element_list)):  # element_index 为第3级索引
                # print(f'第{command_index+1}个指令-第{element_index+1}个元素：',data[command_index]['data'][element_index])
                element = element_list[element_index]
                element_type = element['type']
                element_name = element['name']

                # 检查元素合法性
                result, msg = character_legality_check(element)
                if result == False:
                    return {'result': False, 'msg': f'[字符类型错误]第{line_index}行-第{element_index+1}个元素非法-{msg}'}

                # 开始统计元素类型
                if element_name == '有效时间区间':

                    element_abstract['总数'] += 1
                    element_abstract['有限时间'] += 1
                    element_abstract['时间元素总数'] += 1
                    element_abstract['时间区间'] += 1

                elif element_name == '时间':
                    time_type = element['time_type']  # [内,后]

                    element_abstract['总数'] += 1
                    if time_type == '内':
                        element_abstract['时间']['内'] += 1
                        element_abstract['有限时间'] += 1
                    elif time_type == '后':
                        element_abstract['时间']['后'] += 1
                        element_abstract['无限时间'] += 1

                elif element_name == '时刻':

                    element_abstract['总数'] += 1
                    element_abstract['有限时间'] += 1
                    element_abstract['时间元素总数'] += 1
                    element_abstract['时刻'] += 1

                elif element_name == '价格':
                    # [上穿,下刺,未上穿,未下刺,大于,小于]
                    price_direction = element['price_direction']
                    if price_direction == '上穿':
                        element_abstract['价格']['上穿'] += 1
                        element_abstract['短元素'] += 1
                    elif price_direction == '下刺':
                        element_abstract['价格']['下刺'] += 1
                        element_abstract['短元素'] += 1
                    elif price_direction == '未上穿':
                        element_abstract['价格']['未上穿'] += 1
                        if not_pierced_downgrade:
                            element_abstract['状态元素'] += 1
                        else:
                            element_abstract['长元素'] += 1
                    elif price_direction == '未下刺':
                        element_abstract['价格']['未下刺'] += 1
                        if not_pierced_downgrade:
                            element_abstract['状态元素'] += 1
                        else:
                            element_abstract['长元素'] += 1
                    elif price_direction == '大于':
                        element_abstract['价格']['大于'] += 1
                        element_abstract['瞬间元素'] += 1
                    elif price_direction == '小于':
                        element_abstract['价格']['小于'] += 1
                        element_abstract['瞬间元素'] += 1

                    element_abstract['总数'] += 1

                elif element_name == '净值':
                    # [上穿,下刺,未上穿,未下刺,大于,小于]
                    networth_direction = element['networth_direction']
                    if networth_direction == '上穿':
                        element_abstract['净值']['上穿'] += 1
                        element_abstract['短元素'] += 1
                    elif networth_direction == '下刺':
                        element_abstract['净值']['下刺'] += 1
                        element_abstract['短元素'] += 1
                    elif networth_direction == '未上穿':
                        element_abstract['净值']['未上穿'] += 1
                        if not_pierced_downgrade:
                            element_abstract['状态元素'] += 1
                        else:
                            element_abstract['长元素'] += 1
                    elif networth_direction == '未下刺':
                        element_abstract['净值']['未下刺'] += 1
                        if not_pierced_downgrade:
                            element_abstract['状态元素'] += 1
                        else:
                            element_abstract['长元素'] += 1
                    elif networth_direction == '大于':
                        element_abstract['净值']['大于'] += 1
                        element_abstract['瞬间元素'] += 1
                    elif networth_direction == '小于':
                        element_abstract['净值']['小于'] += 1
                        element_abstract['瞬间元素'] += 1

                    element_abstract['总数'] += 1

                elif element_name == '逻辑运算':
                    logical_operator = element['logical_operator']  # 逻辑运算关系
                    if logical_operator == '且':
                        element_abstract['逻辑运算']['且'] += 1
                    elif logical_operator == '或':
                        element_abstract['逻辑运算']['或'] += 1

                    element_abstract['总数'] += 1
                    element_abstract['逻辑元素'] += 1

            # 计算总数
            # for element_abstract_key in element_abstract:
            #     if isinstance(element_abstract[element_abstract_key], int):
            #         element_abstract['总数'] += element_abstract[element_abstract_key]
            #     else:
            #         for element_abstract_key_second in element_abstract[element_abstract_key]:
            #             element_abstract['总数'] += element_abstract[element_abstract_key][element_abstract_key_second]
            # print(element_abstract)

            # 10.指令的最后一个元素必须为动作指令
            if command_index + 1 == len(data) and element_list[0]['name'] not in ['启动', '平移', '冲刺', '离场']:
                # return {'result': False, 'msg': f'[指令逻辑错误]第{command_index + 1}个指令|指令的最后一个元素必须为动作元素'}
                return {'result': False, 'msg': f'[指令逻辑错误]自动执行策略的最后一个元素必须为动作元素'}
            # 11.指令的第一个元素必须为条件指令
            if data[0]['data'][0]['name'] not in ['有效时间区间', '时间', '价格', '净值', '逻辑运算', '时刻']:
                # return {'result': False, 'msg': f'[指令逻辑错误]第{command_index + 1}个指令|指令的第一个元素必须为条件指令'}
                return {'result': False, 'msg': f'[指令逻辑错误]自动执行策略的第一个元素必须为条件元素'}

            # 计算合理性
            if element_list[0]['name'] in ['有效时间区间', '时间', '价格', '净值', '逻辑运算', '时刻']:
                # 0.时长后+且 跳过
                if element_abstract['时间']['后'] == 1 and element_abstract['逻辑运算']['且'] == 1 and element_abstract['总数'] == 2:
                    # return {'result': True, 'msg': '检查通过'}
                    continue
                # 0-1.时刻+且 跳过
                if element_abstract['时刻'] == 1 and element_abstract['逻辑运算']['且'] == 1 and element_abstract['总数'] == 2:
                    # return {'result': True, 'msg': '检查通过'}
                    continue
                if element_abstract['时刻'] == 1 and element_abstract['总数'] > 2:
                    return {'result': False, 'msg': f'[指令逻辑错误]第{line_index}行|时刻只可以独立使用'}
                # 1.逻辑元素只能有一个:
                if element_abstract['逻辑元素'] != 1:
                    return {'result': False, 'msg': f'[指令逻辑错误]第{line_index}行|"且或"只能有一个'}
                # 2.时间区间只能小于等于1个
                if element_abstract['时间区间'] + element_abstract['时间']['内'] + element_abstract['时间']['后'] >= 2:
                    return {'result': False, 'msg': '[指令逻辑错误]第{line_index}行|只能有一个"时间元素"'}
                # 3.若存在“大于”/“小于”，该指令中不可存在其他元素
                if element_abstract['瞬间元素'] >= 1 and element_abstract['总数'] != 2:
                    return {'result': False, 'msg': f'[指令逻辑错误]第{line_index}行|"大于"/"小于"只能单独使用'}
                # 4.短元素+长元素+瞬间元素 >= 1
                if element_abstract['短元素'] + element_abstract['长元素'] + element_abstract['瞬间元素'] == 0:
                    return {'result': False, 'msg': f'[指令逻辑错误]第{line_index}行|"价格"/"净值"条件不能为空'}
                # 5.时间区间，时长内 不可独立使用
                if element_abstract['时间区间'] == element_abstract['总数'] - 1 or element_abstract['时间']['内'] == element_abstract['总数'] - 1:
                    return {'result': False, 'msg': f'[指令逻辑错误]第{line_index}行|"时间区间"/"时长-内"必须搭配"价格"/"净值"条件使用'}
                # 6.或指令中，短元素+长元素 >= 2
                if element_abstract['逻辑运算']['或'] == 1 and element_abstract['短元素'] + element_abstract['长元素'] < 2:
                    return {'result': False, 'msg': f'[指令逻辑错误]第{line_index}行|只有一个非状态条件元素，无需用"或"'}
                # 7.所有指令不可重复使用
                if element_abstract['时间区间'] >= 2 or element_abstract['时间']['内'] >= 2 or element_abstract['时间']['后'] >= 2 or element_abstract['价格']['上穿'] >= 2 or element_abstract['价格']['下刺'] >= 2 or element_abstract['价格']['未上穿'] >= 2 or element_abstract['价格']['未下刺'] >= 2 or element_abstract['价格']['大于'] >= 2 or element_abstract['价格']['小于'] >= 2 or element_abstract['净值']['上穿'] >= 2 or element_abstract['净值']['下刺'] >= 2 or element_abstract['净值']['未上穿'] >= 2 or element_abstract['净值']['未下刺'] >= 2 or element_abstract['净值']['大于'] >= 2 or element_abstract['净值']['小于'] >= 2 or element_abstract['逻辑运算']['且'] >= 2 or element_abstract['逻辑运算']['或'] >= 2:
                    return {'result': False, 'msg': f'[指令逻辑错误]第{line_index}行|指令元素重复'}
                # 8.且指令中，不可出现两个短指令
                if element_abstract['逻辑运算']['且'] == 1 and element_abstract['短元素'] >= 2:
                    return {'result': False, 'msg': f'[指令逻辑错误]第{line_index}行|"且"指令中，不可出现两个"上穿"/"下刺"'}
                # 9.“价格”/“净值”上穿不可与上穿一起使用、下刺不可与下刺一起使用
                if element_abstract['价格']['上穿'] + element_abstract['价格']['未上穿'] >= 2 or element_abstract['价格']['下刺'] + element_abstract['价格']['未下刺'] >= 2 or element_abstract['净值']['上穿'] + element_abstract['净值']['未上穿'] >= 2 or element_abstract['净值']['下刺'] + element_abstract['净值']['未下刺'] >= 2:
                    return {'result': False, 'msg': f'[指令逻辑错误]第{line_index}行|"上穿"不可与"未上穿"一起使用、"下刺"不可与"未下刺"一起使用'}
                # 12.“分钟后”不可与“未上穿/下刺”一起使用
                if element_abstract['时间']['后'] == 1 and element_abstract['长元素'] > 0:
                    return {'result': False, 'msg': f'[指令逻辑错误]第{line_index}行|“分钟后”不可与“未上穿/下刺”一起使用'}
                # 13.长元素必须搭配有限时间区间使用
                if element_abstract['长元素'] > 0 and element_abstract['有限时间'] == 0:
                    return {'result': False, 'msg': f'[指令逻辑错误]第{line_index}行|“未上穿”/“未下刺”必须与“时间区间”/“时长内”一起使用'}

                # return {'result': False, 'msg': '合法性检查不通过'}
            if element_list[0]['name'] in ['启动', '平移', '冲刺', '离场']:
                element_type = element_list[0]['type']
                element_name = element_list[0]['name']
                element_note = element_list[0]['note']

                #检查note是否存在
                if element_name == '启动':
                    table_name = 'autostart3'
                    status = '草稿'
                elif element_name == '平移':
                    table_name = 'autotranslation3'
                    status = '草稿'
                elif element_name == '冲刺':
                    table_name = 'autosprint3'
                    status = '草稿'
                elif element_name == '离场':
                    table_name = 'autoleave3'
                    status = '草稿'
                else:
                    table_name = ''
                    status = ''

                sql = "SELECT count(*) from %s WHERE status = '%s' and note = '%s' and client = '%s' and contract = '%s' " % ( table_name, status, element_note, client, contract)
                results = tools.mysql_short_get(sql)

                if results[0][0] == 0:
                    return {'result': False, 'msg': f'[动作不存在]第{line_index}行|动作不存在'}

        return {'result': True, 'msg': '检查通过'}
    except BaseException:
        pass
        print(traceback.format_exc())


def dada_in_check_autoexecute3(check_type, data_in):

    in_note = data_in['note']
    in_run_type = data_in['run_type']
    data_in['in_data'] = json.loads(data_in['data'])

    type_check, msg, data_in['note'] = typecheck.is_str(in_note)
    if not type_check:
        return False, f'备注||{msg}', ''

    if len(data_in['in_data']) == 0:
        return respond({'code': 1001, 'date': '', 'msg': '指令未填写'})

    if check_type == '新增':
        pass

    msg = ''
    return True, msg, data_in

# 2.24.1 自动执行
@app.route("/quant/trade/get_autoexecute3", methods=['POST'])
def quant_trade_get_autoexecute3():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']

    sql = "SELECT id,client,contract,data,status,execute_history,note FROM autoexecute3 where client='%s' and contract='%s' " % (in_client, in_contract)
    results = tools.mysql_short_get(sql)

    detail = []

    for result in results:
        temp_dict = {}
        temp_dict['id'] = int(result[0])
        # temp_dict['client'] = result[1]
        # temp_dict['contract'] = result[2]
        data = json.loads(result[3])
        temp_dict['status'] = result[4]
        temp_dict['excute_history'] = result[5]
        temp_dict['note'] = result[6]

        temp_dict['_disabled'] = ''

        # 增加状态嵌套
        for data_single in data:
            # print(data_single)
            status = data_single['status']
            for data_single2 in data_single['data']:
                data_single2['status'] = status

        temp_dict['data'] = data

        detail.append(temp_dict)

    data_out = {'code': 1000, 'data': detail, 'msg': '【自动执行】数据刷新'}
    return respond(data_out)


# 2.24.2新增某用户，某合约的自动执行3
@app.route("/quant/trade/insert_autoexecute3", methods=['POST'])
def quant_trade_insert_autoexecute3():
    data_in = g.data_in

    type_check, msg, data_in = dada_in_check_autoexecute3('新增', data_in)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'{msg}'})

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_data = json.loads(data_in['data'])
    in_note = data_in['note']
    in_run_type = data_in['run_type']

    # 数据初始化，数据修正
    def data_initialize(data):
        data2 = []
        for in_data_single in data:

            for in_data_single_single in in_data_single:
                # print(in_data_single_single)
                in_data_single_single['cal_count'] = 0
                if in_data_single_single['name'] == '价格':
                    in_data_single_single['condition1'] = 'false'
                    in_data_single_single['condition2'] = 'false'

                if in_data_single_single['name'] == '净值':
                    in_data_single_single['condition1'] = 'false'
                    in_data_single_single['condition2'] = 'false'

                if in_data_single_single['name'] == '时间':
                    in_data_single_single['time_reference_point'] = 0
                    in_data_single_single['false_count'] = 0

                if in_data_single_single['name'] == '有效时间区间':
                    in_data_single_single['false_count'] = 0
                    in_data_single_single['initialization'] = 0

                if in_data_single_single['name'] == '时刻':
                    in_data_single_single['false_count'] = 0

                # print(in_data_single_single)
            temp_dict = {'data': in_data_single, 'status': '未执行'}
            if temp_dict['data'][0]['type'] == '条件':
                temp_dict['type'] = '条件'
            if temp_dict['data'][0]['type'] == '动作':
                temp_dict['type'] = '动作'
            data2.append(temp_dict)
        return data2

    data2 = data_initialize(in_data)

    check_result = legality_check(data2,in_client, in_contract)

    if not check_result['result']:
        data_out = {'code': 1001, 'data': False, 'msg': check_result['msg']}
        return respond(data_out)

    if in_run_type == '草稿':
        status = '草稿'
    else:
        status = '运行中'

    execute_history = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' ' + '[创建]初始状态为：' + status

    sql = "INSERT INTO autoexecute3 (`client`, `contract`,  `data`, `status`, `note`,`execute_history` ) VALUES ('%s','%s','%s','%s','%s','%s')" % (in_client, in_contract, str(data2).replace('\'', '\"'), status, in_note, execute_history)
    tools.mysql_short_commit(sql)

    data_out = {'code': 1000, 'data': data_in, 'msg': '【自动执行】保存成功'}
    return respond(data_out)


# 2.24.3修改某用户，某合约的自动执行3
@app.route("/quant/trade/update_autoexecute3", methods=['POST'])
def quant_trade_update_autoexecute3():
    data_in = g.data_in

    in_id = data_in['id']
    in_client = data_in['client']
    in_contract = data_in['contract']
    in_data = json.loads(data_in['data'])
    in_note = data_in['note']

    sql = "SELECT status FROM autoexecute3 WHERE id='%s' " % (in_id)
    results = tools.mysql_short_get(sql)
    if results[0][0] != '草稿':
        data_out = {'code': 1001, 'data': '', 'msg': '非“草稿”状态不能编辑'}
        return respond(data_out)

    check_result = legality_check(in_data, in_client, in_contract)

    if not check_result['result']:
        data_out = {
            'code': 1001,
            'data': False,
            'msg': check_result['msg'],
            'msg_level': 'error',
            'traceback': '',
            'line': sys._getframe().f_lineno}
        return respond(data_out)

    sql = "update autoexecute3 set `data`='%s', `note`='%s' WHERE client = '%s' and contract = '%s' and id='%s' " % (str(in_data).replace('\'', '\"'), in_note, in_client, in_contract, in_id)
    tools.mysql_short_commit(sql)

    data_out = {'code': 1000, 'data': '', 'msg': '【自动执行】编辑成功'}
    return respond(data_out)


# 2.24.4删除某用户，某合约的自动执行3（批量）
@app.route("/quant/trade/delete_autoexecute3_multi", methods=['POST'])
def quant_trade_delete_autoexecute_multi():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_list_id = json.loads(data_in['list_id'])

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for id in in_list_id:
        sql = "DELETE FROM autoexecute3 WHERE client = '%s' and contract = '%s' and id='%s' " % (
            in_client, in_contract, id)
        cursor.execute(sql)
        db.commit()

    db.close()

    data_out = {'code': 1000, 'data': '', 'msg': '【自动执行】删除成功'}
    return respond(data_out)


# 2.24.5激活某用户，某合约的自动执行3（批量）
@app.route("/quant/trade/activate_autoexecute3_multi", methods=['POST'])
def quant_trade_activate_autoexecute_multi():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_list_id = json.loads(data_in['list_id'])

    total_count = len(in_list_id)
    valid_count = 0

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor()
    for id in in_list_id:
        # 查看当前状态
        sql = "SELECT status FROM autoexecute3 where client='%s' and contract='%s' and id = '%s' " % (
            in_client, in_contract, id)
        cursor.execute(sql)  # 执行SQL语句
        results = cursor.fetchall()  # 获取所有记录列表

        if results[0][0] != '草稿':
            data_out = {'code': 1001, 'data': '', 'msg': '当前状态不能激活'}
        else:
            sql = "update autoexecute3 set status = '运行中' WHERE client = '%s' and contract = '%s' and id='%s' and status = '草稿' " % (in_client, in_contract, id)
            cursor.execute(sql)
            db.commit()

            execute_history = '\n' + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + ' ' + '[激活]' + g.device
            sql = "UPDATE autoexecute3 SET `execute_history` = CONCAT (`execute_history`,'%s') WHERE id = '%s' " % (execute_history, id)
            cursor.execute(sql)
            db.commit()

            valid_count += 1

    db.close()

    if valid_count == total_count:
        data_out = {'code': 1000, 'data': '', 'msg': '【自动执行】选中运行成功'}
    elif valid_count == 0:
        data_out = {'code': 1001, 'data': '', 'msg': '【自动执行】选中运行失败'}
    else:
        data_out = {'code': 1000, 'data': '', 'msg': '【自动执行】选中运行部分成功'}

    return respond(data_out)


# 5.1获取量化监控列表
@app.route("/quant/monitor/get_list_monitor", methods=['POST'])
def quant_monitor_get_list_monitor():
    data_in = g.data_in

    if g.level == 'admin':
        sql = "SELECT name,swap_margin_balance,下终止,上终止,止损时间,swap_buy_volume,swap_sell_volume,swap_profit_unreal,count_of_orders_active,多单强平点,空单强平点,多单最大仓位,空单最大仓位,swap_margin_available,swap_margin_frozen,lowest_net_worth,contract,open_or_close,swap_margin_position,buy_straight_up,buy_straight_down,buy_cycle_up,buy_cycle_down,sell_straight_up,sell_straight_down,sell_cycle_up,sell_cycle_down,account_straight_up,account_straight_down,account_cycle_up,account_cycle_down,profit_loss_cal_status_unrun,swap_buy_lever_rate,count_of_orders_exchange,highest_net_worth,当前强平点,adl FROM information_client"

    elif g.level == 'trader':
        sql = "SELECT name,swap_margin_balance,下终止,上终止,止损时间,swap_buy_volume,swap_sell_volume,swap_profit_unreal,count_of_orders_active,多单强平点,空单强平点,多单最大仓位,空单最大仓位,swap_margin_available,swap_margin_frozen,lowest_net_worth,contract,open_or_close,swap_margin_position,buy_straight_up,buy_straight_down,buy_cycle_up,buy_cycle_down,sell_straight_up,sell_straight_down,sell_cycle_up,sell_cycle_down,account_straight_up,account_straight_down,account_cycle_up,account_cycle_down,profit_loss_cal_status_unrun,swap_buy_lever_rate,count_of_orders_exchange,highest_net_worth,当前强平点,adl FROM information_client where trader = '%s'" % (g.user)
    else:
        sql = ''
    results = tools.mysql_short_get(sql)

    temp_list = []
    for result in results:
        temp_dict = {}
        temp_dict['name'] = result[0]
        temp_dict['contract'] = result[16]
        contract = temp_dict['contract']
        temp_dict['margin_balance'] = tools.get_display_number(number=result[1], contract=contract)

        price_dict = tools.get_price_dict()
        price_index = tools.get_price(price_dict, contract_code=temp_dict['contract'], price_type='指数价')  # 获取最新价
        price_now = tools.get_price(price_dict, contract_code=temp_dict['contract'], price_type='市价')  # 获取最新价
        temp_dict['cny'] = str(round(float(result[1]) * float(price_index), 1)) if 'USDT' not in contract else str(round(float(result[1]) / price_now * price_index, 1))
        temp_dict['end_down'] = result[2]
        temp_dict['end_up'] = result[3]
        temp_dict['end_time'] = result[4]
        if temp_dict['end_time'] != 'None':
            temp_dict['end_time'] = float(temp_dict['end_time']) * 1000
        temp_dict['buy_volume'] = int(float(result[5]))
        temp_dict['sell_volume'] = int(float(result[6]))
        temp_dict['profit_unreal'] = tools.get_display_number(number=result[7], contract=contract)
        temp_dict['count_of_active_orders'] = '本地:' + result[8] + ',' + '交易所:' + result[33]
        temp_dict['liquidation_buy'] = result[9]
        temp_dict['liquidation_sell'] = result[10]
        temp_dict['buy_volume_max'] = result[11]
        temp_dict['sell_volume_max'] = result[12]
        temp_dict['margin_available'] = tools.get_display_number(number=result[13], contract=contract)
        temp_dict['margin_frozen'] = tools.get_display_number(number=result[14], contract=contract)
        temp_dict['lowest_net_worth'] = round(float(result[15]), 6) if result[15] != 'None' else 'None'
        temp_dict['open_or_close'] = result[17]
        temp_dict['margin_position'] = tools.get_display_number(number=result[18], contract=contract)

        temp_dict['contract_unit'] = ' USDT' if 'USDT' in contract else ' BTC'
        temp_dict['legal_currency_unit'] = '$'
        # 开始构建盈亏数据
        buy_straight_up = tools.get_display_number(number=result[19], contract=contract)
        buy_straight_down = tools.get_display_number(number=result[20], contract=contract)
        buy_cycle_up = tools.get_display_number(number=result[21], contract=contract)
        buy_cycle_down = tools.get_display_number(number=result[22], contract=contract)
        sell_straight_up = tools.get_display_number(number=result[23], contract=contract)
        sell_straight_down = tools.get_display_number(number=result[24], contract=contract)
        sell_cycle_up = tools.get_display_number(number=result[25], contract=contract)
        sell_cycle_down = tools.get_display_number(number=result[26], contract=contract)
        account_straight_up = tools.get_display_number(number=result[27], contract=contract)
        account_straight_down = tools.get_display_number(number=result[28], contract=contract)
        account_cycle_up = tools.get_display_number(number=result[29], contract=contract)
        account_cycle_down = tools.get_display_number(number=result[30], contract=contract)
        profit_loss_cal_status_unrun = result[31]
        lever_rate = result[32]
        highest_net_worth = result[34]

        try:
            temp_dict['max_profit_and_loss_data'] = [{'name': '空单',
                                                      'c1': sell_straight_up,
                                                      'c1_color': False,
                                                      'c2': sell_cycle_up,
                                                      'c2_color': False,
                                                      'c3': sell_straight_down,
                                                      'c3_color': False,
                                                      'c4': sell_cycle_down,
                                                      'c4_color': False},
                                                     {'name': '多单',
                                                      'c1': buy_straight_up,
                                                      'c1_color': False,
                                                      'c2': buy_cycle_up,
                                                      'c2_color': False,
                                                      'c3': buy_straight_down,
                                                      'c3_color': False,
                                                      'c4': buy_cycle_down,
                                                      'c4_color': False},
                                                     {'name': '账户',
                                                      'c1': account_straight_up,
                                                      'c1_color': False if float(result[1]) + float(result[27]) > 0 else True,
                                                      'c2': account_cycle_up,
                                                      'c2_color': False if float(result[1]) + float(result[29]) > 0 else True,
                                                      'c3': account_straight_down,
                                                      'c3_color': False if float(result[1]) + float(result[28]) > 0 else True,
                                                      'c4': account_cycle_down,
                                                      'c4_color': False if float(result[1]) + float(result[30]) > 0 else True}]
        except:
            temp_dict['max_profit_and_loss_data'] = [
                {'name': '空单', 'c1': sell_straight_up, 'c1_color': True, 'c2': sell_cycle_up, 'c2_color': True,
                 'c3': sell_straight_down, 'c3_color': True, 'c4': sell_cycle_down, 'c4_color': True},
                {'name': '多单', 'c1': buy_straight_up, 'c1_color': True, 'c2': buy_cycle_up, 'c2_color': True,
                 'c3': buy_straight_down, 'c3_color': True, 'c4': buy_cycle_down, 'c4_color': True},
                {'name': '账户', 'c1': account_straight_up, 'c1_color': True, 'c2': account_cycle_up, 'c2_color': True,
                 'c3': account_straight_down, 'c3_color': True, 'c4': account_cycle_down, 'c4_color': True}
            ]

        # 盈亏计算是否包含未启动滑块
        def str_to_bool(str):
            if str == 'True':
                return True
            else:
                return False

        temp_dict['profit_loss_cal_status_unrun'] = str_to_bool(
            profit_loss_cal_status_unrun)
        temp_dict['lever_rate'] = lever_rate + 'X'
        temp_dict['highest_net_worth'] = round(float(highest_net_worth),6) if highest_net_worth != 'None' else 'None'
        temp_dict['liquidation_price'] = str(round(float(result[35]), 2)) if result[35] != '--' else '--'

        temp_dict['adl'] = result[36]

        temp_list.append(temp_dict)

    temp_list.sort(key=lambda s: s['contract'])
    temp_data_out = temp_list

    return respond({'code': 1000, 'data': temp_data_out, 'msg': '数据刷新'})


# 6.1获取会员列表
@app.route("/quant/client/get_list_client", methods=['POST'])
def quant_client_get_list_client():
    data_in = g.data_in

    if g.level == 'admin':
        sql = "SELECT name,trader,apikey,secretkey,swap_margin_balance,contract FROM information_client "
        results = tools.mysql_short_get(sql)

        temp_list = []
        for result in results:
            temp_dict = {}
            temp_dict['client_name'] = result[0]
            temp_dict['trader'] = result[1]
            temp_dict['apikey'] = result[2]
            temp_dict['secretkey'] = '******'
            temp_dict['swap_margin_balance'] = tools.get_display_number(number=result[4], contract=result[5])
            temp_dict['margin_frozen'] = '--'
            temp_dict['lowest_net_worth'] = '--'
            temp_dict['lowest_net_worth_type'] = '--'
            temp_dict['swap_margin_available'] = '--'
            temp_dict['swap_margin_position'] = '--'
            temp_dict['highest_net_worth'] = '--'
            temp_dict['highest_net_worth_type'] = '--'

            if temp_dict not in temp_list:
                temp_list.append(temp_dict)

        temp_data_out = temp_list
    else:
        temp_data_out = '权限不足'
    data_out = {'code': 1000, 'data': temp_data_out}
    return respond(data_out)


# 6.2添加新会员（新客户）
@app.route("/quant/client/insert_client", methods=['POST'])
def quant_client_insert_client():
    data_in = g.data_in
    try:
        if g.level == 'admin':
            client_name = data_in['client_name']
            apikey = data_in['apikey']
            secretkey = data_in['secretkey']
            contract = data_in['account_type']
            apipassword = data_in['password']

            def add_new_client_main(client_name, apikey, secretkey, contract, apipassword):
                # 重名检查
                sql = "SELECT * FROM information_client WHERE name='%s'  " % (client_name)
                results = tools.mysql_short_get(sql)

                if len(results) != 0:
                    return '出现重名,添加失败'

                # 1.检查秘钥是否有效
                apikey = apikey
                secretkey = secretkey
                passphrase = apipassword
                flag = '0' if config['real_trading'] else '1'

                content_header = '[api_trade]'
                ouyiapi = OuyiAPI.RestAPI(api_key=apikey, secret_key=secretkey, passphrase=passphrase, flag=flag, logger=logger_content, content_header=content_header, alarm=Alarm(db_info=config['db_info']))
                results = ouyiapi.get_account_config()  # 返回值包含uid数据

                if results['code'] == '1':
                    return '秘钥无效,添加失败'

                temp_uid = results['data'][0]['uid']

                # 3.写入information_client
                def add_new_client(client_name, contract):
                    sql = "INSERT INTO information_client (trader,name,apikey,secretkey,uid,start_order_status,start_cal_status,start_do_status,下终止,上终止,止损时间,account_status,swap_margin_balance,swap_margin_static," \
                          "swap_margin_position,swap_margin_frozen,swap_margin_available,swap_profit_real,swap_profit_unreal,swap_risk_rate,swap_liquidation_price,swap_withdraw_available,swap_lever_rate,swap_adjust_factor," \
                          "swap_buy_volume,swap_buy_available,swap_buy_frozen,swap_buy_cost_open,swap_buy_cost_hold,swap_buy_profit_unreal,swap_buy_profit_rate,swap_buy_profit,swap_buy_position_margin," \
                          "swap_buy_lever_rate,swap_buy_direction,swap_sell_volume,swap_sell_available,swap_sell_frozen,swap_sell_cost_open,swap_sell_cost_hold,swap_sell_profit_unreal,swap_sell_profit_rate," \
                          "swap_sell_profit,swap_sell_position_margin,swap_sell_lever_rate,swap_sell_direction,end_up_type,end_down_type,end_time_type,end_up_price_type,end_down_price_type,lowest_net_worth," \
                          "lowest_net_worth_type,open_or_close,contract,start_order_pid,start_cal_pid,start_do_pid,profit_loss_cal_status_unrun,buy_straight_up,buy_straight_down,buy_cycle_up,buy_cycle_down," \
                          "sell_straight_up,sell_straight_down,sell_cycle_up,sell_cycle_down,account_straight_up,account_straight_down,account_cycle_up,account_cycle_down,passphrase,count_of_orders_active," \
                          "count_of_orders_exchange,当前强平点,highest_net_worth,highest_net_worth_type,cycle_waiting_time,maker_fee,taker_fee,maker_delta) VALUES" \
                          "('%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s','%s')" % \
                          ('None', client_name, apikey, secretkey, temp_uid, '未启动', '未启动', '未启动', 'None', 'None', 'None', 'normal', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '被动', '被动', '被动', '市价', '市价', 'None', '主动', '开启', contract, '0', '0', '0',
                           'True', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', apipassword, '0', '0', '--', 'None', '主动', '60', '0.0002', '0.0005', '1')
                    tools.mysql_short_commit(sql)

                add_new_client(client_name, contract)

                return '新用户添加成功'

            temp_return = add_new_client_main(client_name, apikey, secretkey, contract, apipassword)
            if temp_return == '出现重名,添加失败':
                data_out = {'code': 1006, 'data': '出现重名,添加失败'}
            elif temp_return == '秘钥无效,添加失败':
                data_out = {'code': 1005, 'data': '秘钥无效'}
            elif temp_return == '新用户添加成功':
                data_out = {'code': 1000, 'data': '新用户添加成功'}
            else:
                temp_data_out = '业务正常'
                data_out = {'code': 1000, 'data': temp_data_out}
        else:
            data_out = {'code': 1004, 'data': '权限不足'}
    except:
        data_out = {'code': 1001, 'data': {'msg': '业务异常', 'traceback': traceback.format_exc()}}

    return respond(data_out)


# 6.3删除会员（客户）
@app.route("/quant/client/delete_client", methods=['POST'])
def quant_client_delete_client():
    data_in = g.data_in

    if g.level == 'admin':
        client_name = data_in['client_name']

        sql = "SELECT count(*) FROM strategy_parameter_cycle_run where client_name='%s' " % (client_name)
        results = tools.mysql_short_get(sql)

        if results[0][0] == 0:

            db = pymysql.connect(user=mysql_user,password=mysql_password,host=mysql_host,port=mysql_port,db=mysql_db,charset=mysql_charset)
            cursor = db.cursor()

            # 5.删除 preset
            sql = "DELETE FROM strategy_parameter_cycle_preset WHERE client_name = '%s' " % (client_name)
            cursor.execute(sql)  # 执行SQL语句
            db.commit()

            # 8.删除networth
            sql = "DELETE FROM networth_client WHERE client = '%s' " % (client_name)
            cursor.execute(sql)  # 执行SQL语句
            db.commit()

            sql = "update information_client set start_cal_status='待关闭' where name = '%s' " % (client_name)
            cursor.execute(sql)  # 执行SQL语句
            db.commit()

            db.close()

            temp_data_out = '删除成功'
            data_out = {'code': 1000, 'data': temp_data_out}
        else:
            temp_data_out = '当前账户存在未删除策略，请先清空策略！'
            data_out = {'code': 1007, 'data': temp_data_out}
    else:
        data_out = {'code': 1004, 'data': '权限不足'}

    return respond(data_out)


# 7.1获取子管理员列表（交易员列表）
@app.route("/quant/trader/get_list_trader", methods=['POST'])
def quant_trader_get_list_trader():
    data_in = g.data_in

    try:
        sql = "SELECT `name`,`googlekey` FROM information_user where level = 'trader' "
        results = tools.mysql_short_get(sql)

        temp_list = []
        for result in results:
            temp_dict = {}
            temp_dict['trader'] = result[0]

            sql = "SELECT name FROM information_client where trader='%s' " % (result[0])
            results2 = tools.mysql_short_get(sql)

            temp_list_cal_len = []
            for temp_results2 in results2:
                if temp_results2[0] not in temp_list_cal_len:
                    temp_list_cal_len.append(temp_results2[0])
            temp_dict['client_number'] = len(temp_list_cal_len)

            temp_dict['trader'] = result[0]
            if result[1] == 'None':
                temp_dict['googlekey'] = 'None'
            else:
                temp_dict['googlekey'] = 'exist'
            temp_list.append(temp_dict)

        data_out = {'code': 1000, 'data': {'list_trader': temp_list}}
    except:
        data_out = {'code': 1001, 'data': {'msg': '业务异常'}}
    return respond(data_out)


# 7.2获取子管理员（交易员）所管理会员（客户）列表
@app.route("/quant/trader/get_list_trader_client", methods=['POST'])
def quant_trader_get_list_trader_client():
    try:
        data_in = g.data_in

        in_trader = data_in['in_trader']

        sql = "SELECT name FROM information_client where trader='%s' " % (in_trader)
        results = tools.mysql_short_get(sql)

        temp_list = []
        for result in results:
            if result not in temp_list:
                temp_list.append(result)

        data_out = {'code': 1000, 'data': {'list_client': temp_list}}
    except:
        data_out = {'code': 1001, 'data': {'msg': '业务异常'}}
    return respond(data_out)


# 7.3获取某交易员已分配列表和尚未分配管理员的会员（客户）列表
@app.route("/quant/trader/get_list_trader_none", methods=['POST'])
def quant_trader_get_list_trader_none():
    try:
        data_in = g.data_in

        in_trader = data_in['trader']

        temp_list_distributed = []
        sql = "SELECT name FROM information_client where trader='%s' " % (in_trader)
        results = tools.mysql_short_get(sql)

        for result in results:
            if result[0] not in temp_list_distributed:
                temp_list_distributed.append(result[0])

        temp_list_undistributed = []
        sql = "SELECT name FROM information_client where trader='%s' " % ('None')
        results2 = tools.mysql_short_get(sql)

        for result2 in results2:
            temp_dict = {}
            temp_dict['key'] = result2[0]
            temp_dict['label'] = result2[0]
            if temp_dict not in temp_list_undistributed:
                temp_list_undistributed.append(temp_dict)

        for result in results:
            temp_dict = {}
            temp_dict['key'] = result[0]
            temp_dict['label'] = result[0]
            if temp_dict not in temp_list_undistributed:
                temp_list_undistributed.append(temp_dict)

        data_out = {'code': 1000, 'data': {'temp_list_undistributed': temp_list_undistributed, 'temp_list_distributed': temp_list_distributed}}
    except:
        data_out = {'code': 1001, 'data': {'msg': '业务异常'}}
    return respond(data_out)


# 7.4添加子管理员（交易员）
@app.route("/quant/trader/insert_trader", methods=['POST'])
def quant_trader_insert_trader():
    try:
        data_in = g.data_in

        in_name = data_in['trader']
        in_googlecode = data_in['googlecode']  # 历史遗留问题，此处指 16位随机字符串
        in_googlekey = data_in['googlekey']  # 历史遗留问题，此处指 6位数字验证码

        # 重名检查
        sql = "SELECT * FROM information_user WHERE name='%s'  " % (in_name)
        results = tools.mysql_short_get(sql)

        if len(results) != 0:
            data_out = {'code': 1017, 'data': '管理员已存在，请检查后重新添加'}
            return respond(data_out)

        if str(in_googlekey) == str(calGoogleCode(in_googlecode)):
            sql = "INSERT INTO information_user (`name`,`key`,`level`,`googlekey`) VALUES ('%s','%s','%s','%s') " % (in_name, '123456', 'trader', in_googlecode)
            tools.mysql_short_commit(sql)

            data_out = {'code': 1000, 'data': '业务正常'}
        else:
            data_out = {'code': 1008, 'data': '谷歌验证码错误'}
    except:
        data_out = {'code': 1001, 'data': {'msg': '业务异常'}}
    return respond(data_out)


# 7.5删除子管理员（交易员）
@app.route("/quant/trader/delete_trader", methods=['POST'])
def quant_trader_delete_trader():
    try:
        data_in = g.data_in

        in_trader = data_in['trader']

        db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
        cursor = db.cursor()

        sql = "UPDATE information_client SET `trader` = '%s' where trader='%s' " % ('None', in_trader)
        cursor.execute(sql)  # 执行SQL语句
        db.commit()

        sql = "DELETE FROM information_user WHERE name='%s' " % (in_trader)
        cursor.execute(sql)
        db.commit()

        sql = "DELETE  FROM networth_trader WHERE trader = '%s' " % (in_trader)
        cursor.execute(sql)
        db.commit()

        db.close()

        data_out = {'code': 1000, 'data': '业务正常'}
    except:
        data_out = {'code': 1001, 'data': {'msg': '业务异常'}}
    return respond(data_out)


# 7.6重置子管理员（交易员）登录密码为 123456
@app.route("/quant/trader/default_trader_password", methods=['POST'])
def quant_trader_default_trader_password():
    try:
        data_in = g.data_in

        in_trader = data_in['trader']

        sql = "UPDATE information_user SET `key` = '123456' where name='%s' " % (in_trader)
        tools.mysql_short_commit(sql)

        data_out = {'code': 1000, 'data': '业务正常'}
    except:
        data_out = {'code': 1001, 'data': {'msg': '业务异常'}}
    return respond(data_out)


# 7.7更新子管理员（交易员）googlekey
@app.route("/quant/trader/update_trader_googlekey", methods=['POST'])
def quant_trader_update_trader_googlekey():
    try:
        data_in = g.data_in

        in_tarder = data_in['trader']
        in_googlecode = data_in['googlecode']  # 历史遗留问题，此处指 16位随机字符串
        in_googlekey = data_in['googlekey']  # 历史遗留问题，此处指 6位数字验证码

        if str(in_googlekey) == str(calGoogleCode(in_googlecode)):
            # 此处若需要将某客户至于无交易员状态，需要在tarder字段传入 'None'
            sql = " UPDATE information_user SET `googlekey` = '%s' WHERE NAME = '%s' " % (in_googlecode, in_tarder)
            tools.mysql_short_commit(sql)

            data_out = {'code': 1000, 'data': '业务正常'}
        else:
            data_out = {'code': 1008, 'data': '谷歌验证码错误'}
    except:
        data_out = {'code': 1001, 'data': {'msg': traceback.format_exc()}}
    return respond(data_out)


# 7.8更新子管理员（交易员）登录密码
@app.route("/quant/trader/update_trader_password", methods=['POST'])
def quant_trader_update_trader_password():
    try:
        data_in = g.data_in

        in_trader = data_in['trader']
        in_password = data_in['password']
        in_googlekey = data_in['googlekey']  # 历史遗留问题，此处指 6位数字验证码

        # 先效验谷歌验证码
        sql = "SELECT `googlekey` FROM information_user where name = '%s' " % (in_trader)
        results = tools.mysql_short_get(sql)
        googlekey = results[0][0]

        if str(in_googlekey) == calGoogleCode(googlekey):
            # 谷歌验证码效验成功，开始改密码
            sql = "UPDATE information_user SET `key` = '%s' where name='%s' " % (in_password, in_trader)
            tools.mysql_short_commit(sql)

            data_out = {'code': 1000, 'data': '业务正常'}
        else:
            data_out = {'code': 1008, 'data': '谷歌验证码错误'}
    except:
        data_out = {'code': 1001, 'data': {'msg': '业务异常'}}
    return respond(data_out)


# 7.9更新会员（客户）所属交易员
@app.route("/quant/trader/update_client_trader", methods=['POST'])
def quant_trader_update_client_trader():
    try:
        data_in = g.data_in

        in_trader = data_in['trader']
        in_list_all = data_in['undistributed']
        in_list_distributed = data_in['distributed']

        in_list_all = tuple(in_list_all.split(","))
        in_list_distributed = tuple(in_list_distributed.split(","))

        in_list_undistributed = []
        for i in in_list_all:
            if i not in in_list_distributed:
                in_list_undistributed.append(i)

        for in_undistributed in in_list_undistributed:
            sql = "UPDATE information_client SET trader = '%s' where name='%s' " % ('None', in_undistributed)
            tools.mysql_short_commit(sql)

        for in_distributed in in_list_distributed:
            sql = "UPDATE information_client SET trader = '%s' where name='%s' " % (in_trader, in_distributed)
            tools.mysql_short_commit(sql)

        data_out = {'code': 1000, 'data': '业务正常'}
    except:
        data_out = {'code': 1001, 'data': {'msg': '业务异常'}}
    return respond(data_out)


# 7.10一键平仓
@app.route("/quant/trader/end", methods=['POST'])
def quant_trader_end():
    data_in = g.data_in

    in_trader = data_in['trader']

    if g.level == 'admin':

        sql = "UPDATE information_client SET account_status = '终止' WHERE trader = '%s' " % (in_trader)
        tools.mysql_short_commit(sql)

        data_out = {'code': 1000, 'data': '业务正常'}
    else:
        data_out = {'code': 1004, 'data': '权限不足'}
    return respond(data_out)


# 8.1运营统计_获取账户列表
@app.route("/quant/statistics/get_client_list", methods=['POST'])
def quant_statistics_get_client_list():
    data_in = g.data_in

    if g.user == '001':
        # 返回所有用户id
        sql = "SELECT name,trader,contract FROM information_client "
    else:
        # 查询当前交易员管理的账户
        sql = "SELECT name,trader,contract FROM information_client where trader='%s' " % (g.user)

    results = tools.mysql_short_get(sql)

    data_out = {'clients': [], 'ccy': {}}

    for result in results:
        client = result[0]
        trader = result[1]
        contract = result[2]

        if client not in data_out['clients']:
            data_out['clients'].append(client)
            data_out['ccy'][client] = []

            # 添加币种
            ccy_trade = contract.split('-')[0]

            data_out['ccy'][client].append(ccy_trade)
            data_out['ccy'][client].append('USDT')
            if 'BTC' not in data_out['ccy'][client]:
                data_out['ccy'][client].append('BTC')

    return respond({'code': 1000, 'data': data_out, 'msg': ''})


# 8.2运营统计_获取账户净值
@app.route("/quant/statistics/get_statistics", methods=['POST'])
def quant_statistics_get_statistics():
    data_in = g.data_in

    in_level = data_in['level']  # trader,client 管理员总资产与账户资产
    in_unit = data_in['unit']
    in_start_time = float(data_in['start_time']) / 1000
    in_end_time = float(data_in['end_time']) / 1000

    if in_level == 'trader':
        in_trader = g.user
        sql = "SELECT networth,timestamp FROM networth_trader where trader = '%s' and timestamp >= '%s' and timestamp < '%s' and ccy = '%s' " % (in_trader, in_start_time, in_end_time, in_unit)

    elif in_level == 'client':
        in_client = data_in['client']
        sql = "SELECT networth,timestamp FROM networth_client where client = '%s' and timestamp >= '%s' and timestamp < '%s' and ccy = '%s' " % (in_client, in_start_time, in_end_time, in_unit)

    results = tools.mysql_short_get(sql)

    temp_list = []
    append_status = False
    for result in results:
        networth = round(float(result[0]), 8)
        timestamp = int(float(result[1]) * 1000)
        if append_status == False and networth != 0:
            append_status = True

        if append_status:
            temp_list.append([timestamp, networth])

    return respond({'code': 1000, 'data': {'list_networth': temp_list}, 'msg': '运营统计刷新'})


# 9.1 获取账户交易参数
@app.route("/quant/client_config/get_list_client_config", methods=['POST'])
def quant_client_config_get_list_client_config():
    data_in = g.data_in

    if g.level == 'admin':
        sql = "SELECT name,contract,highest_net_worth,highest_net_worth_type,lowest_net_worth,lowest_net_worth_type,cycle_waiting_time,maker_fee,taker_fee,maker_delta FROM information_client  "
    else:
        sql = "SELECT name,contract,highest_net_worth,highest_net_worth_type,lowest_net_worth,lowest_net_worth_type,cycle_waiting_time,maker_fee,taker_fee,maker_delta FROM information_client where trader = '%s' " % (g.user)

    db = pymysql.connect(user=mysql_user, password=mysql_password, host=mysql_host, port=mysql_port, db=mysql_db, charset=mysql_charset)
    cursor = db.cursor(pymysql.cursors.DictCursor)
    cursor.execute(sql)
    results = cursor.fetchall()
    db.close()

    data_out = []
    for result in results:
        result['client'] = result['name']
        del result['name']

        result['maker_fee'] = ('%.10f' % (float(result['maker_fee'])*100)).rstrip('0')
        result['taker_fee'] = ('%.10f' % (float(result['taker_fee'])*100)).rstrip('0')

        data_out.append(result)

    data_out = {'code': 1000, 'data': data_out, 'msg': '账户参数刷新成功'}
    return respond(data_out)


# 9.2 编辑账户交易参数
@app.route("/quant/client_config/update_client_config", methods=['POST'])
def quant_client_config_update_client_config():
    data_in = g.data_in

    in_client = data_in['client']
    in_contract = data_in['contract']
    in_highest_net_worth = data_in['highest_net_worth']
    in_highest_net_worth_type = data_in['highest_net_worth_type']
    in_lowest_net_worth = data_in['lowest_net_worth']
    in_lowest_net_worth_type = data_in['lowest_net_worth_type']
    in_cycle_waiting_time = data_in['cycle_waiting_time']
    in_maker_fee = data_in['maker_fee']
    in_taker_fee = data_in['taker_fee']
    in_maker_delta = data_in['maker_delta']

    # 字符检查
    if in_lowest_net_worth != 'None':
        type_check, msg, in_lowest_net_worth = typecheck.is_posfloat(in_lowest_net_worth)
        if not type_check:
            return respond({'code': 1001, 'data': '', 'msg': f'最低净值||{msg}'})
    if in_lowest_net_worth_type not in ['主动', '被动']:
        return respond({'code': 1001, 'data': '', 'msg': '最低净值平仓方式不合法'})

    if in_highest_net_worth != 'None':
        type_check, msg, in_highest_net_worth = typecheck.is_posfloat(in_highest_net_worth)
        if not type_check:
            return respond({'code': 1001, 'data': '', 'msg': f'最高净值||{msg}'})
    if in_highest_net_worth_type not in ['主动', '被动']:
        return respond({'code': 1001, 'data': '', 'msg': '最高净值平仓方式不合法'})

    type_check, msg, in_cycle_waiting_time = typecheck.is_posfloat(in_cycle_waiting_time, float_max=100000000)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'循环等待时间||{msg}'})

    type_check, msg, in_maker_fee = typecheck.is_float(in_maker_fee, decimal_place=8)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'maker手续费||{msg}'})
    in_maker_fee = in_maker_fee/100

    type_check, msg, in_taker_fee = typecheck.is_float(in_taker_fee, decimal_place=8)
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'taker手续费||{msg}'})
    in_taker_fee = in_taker_fee/100

    type_check, msg, in_maker_delta = typecheck.is_posfloat(in_maker_delta, decimal_place=tools.get_contract_precision(in_contract))
    if not type_check:
        return respond({'code': 1001, 'data': '', 'msg': f'被动间隔||{msg}'})

    # 安全检查
    sql = "SELECT swap_margin_balance FROM  information_client WHERE name = '%s' " % (in_client)
    results = tools.mysql_short_get(sql)
    swap_margin_balance = float(results[0][0])

    if in_highest_net_worth != 'None':
        in_highest_net_worth = float(in_highest_net_worth) * 10000 if 'USDT' in in_contract else float(in_highest_net_worth)
        if in_highest_net_worth <= swap_margin_balance:
            return respond({'code': 1001, 'data': '', 'msg': '最高净值不能小于当前权益'})

    if in_lowest_net_worth != 'None':
        in_lowest_net_worth = float(in_lowest_net_worth) * 10000 if 'USDT' in in_contract else float(in_lowest_net_worth)
        if in_lowest_net_worth >= swap_margin_balance:
            return respond({'code': 1001, 'data': '', 'msg': '最低净值不能大于当前权益'})

    sql = "UPDATE information_client SET lowest_net_worth = '%s',lowest_net_worth_type = '%s',highest_net_worth = '%s',highest_net_worth_type = '%s',cycle_waiting_time = '%s',maker_fee = '%s',taker_fee = '%s',maker_delta = '%s' WHERE name = '%s' and contract = '%s' " % (in_lowest_net_worth, in_lowest_net_worth_type, in_highest_net_worth, in_highest_net_worth_type, in_cycle_waiting_time, in_maker_fee, in_taker_fee, in_maker_delta, in_client, in_contract)
    tools.mysql_short_commit(sql)

    data_out = {'code': 1000, 'data': '', 'msg':'账户参数编辑成功'}
    return respond(data_out)


@app.route("/test/get_liquidation_paramter", methods=['POST'])
def test_get_liquidation_paramter():
    data_in = g.data_in

    client = data_in['client']
    contract = data_in['contract']

    config_server_name = config['server_name']
    config_server_exchange = config['server_exchange']
    config_real_trading = config['real_trading']
    config_db_info = config['db_info']
    config_loggerbackupcount = config['loggerbackupcount']
    config_ding_info = config['ding_info']
    config_urls = config['exchange'][config_server_exchange][config_real_trading]['urls']
    config_contracts = config['exchange'][config_server_exchange][config_real_trading]['contracts']
    config_liquidation = config['exchange'][config_server_exchange][config_real_trading]['liquidation']
    config_rest_errors = config['exchange'][config_server_exchange]['rest_errors']

    # print(f'config_contracts:{config_contracts}')
    # print(f'config_liquidation:{config_liquidation}')

    # 转换合约为强平参数的写法
    if 'SWAP' in contract:
        contract_type = contract
    else:
        contract_type = f"{contract.split('-')[0]}-{contract.split('-')[1]}-FUTURES"

    # 请求样例
    # strategyList = [
    #     {'id': '1', 'direction': '多', 'open': '53700', 'close': '54100', 'volume': '400', 'orderId': '1243143'},
    #     {'id': '2', 'direction': '多', 'open': '53600', 'close': '54000', 'volume': '100', 'orderId': ''},
    #     {'id': '3', 'direction': '多', 'open': '53500', 'close': '53900', 'volume': '100', 'orderId': ''},
    #     {'id': '4', 'direction': '多', 'open': '53400', 'close': '53800', 'volume': '100', 'orderId': ''},
    #     {'id': '5', 'direction': '多', 'open': '53300', 'close': '53700', 'volume': '100', 'orderId': ''},
    #     {'id': '6', 'direction': '多', 'open': '53200', 'close': '53600', 'volume': '100', 'orderId': ''},
    #     {'id': '100', 'direction': '空', 'open': '54200', 'close': '53600', 'volume': '500', 'orderId': '433636'},
    #     {'id': '100', 'direction': '空', 'open': '54300', 'close': '53700', 'volume': '200', 'orderId': ''},
    #     {'id': '100', 'direction': '空', 'open': '54400', 'close': '53800', 'volume': '200', 'orderId': ''},
    #     {'id': '100', 'direction': '空', 'open': '54500', 'close': '53900', 'volume': '100', 'orderId': ''},
    #     {'id': '100', 'direction': '空', 'open': '54600', 'close': '54000', 'volume': '100', 'orderId': ''}
    # 若为未持仓 orderId为空,若有仓位 orderId非空
    # ]
    # serviceChargeRate = '0.0002'  # 手续费率
    # parValue = '100'  # 面值
    # multiple = '125'  # 杠杆倍数
    # upPosition = '400'  # 多方持仓
    # upAveragePositionPrice = '53700'  # 多方持仓均价
    # downPosition = '500'  # 空方持仓
    # downAveragePositionPrice = '54200'  # 空方持仓均价
    # staticBalance = '0.1'  # 静态权益
    # shortNumber = '5'  # 空方策略数
    # buyNumber = '6'  # 多方策略数

    # 查询手续费率
    sql = "SELECT maker_fee,taker_fee FROM information_client where name = '%s' and contract = '%s' " % (client, contract)
    results = tools.mysql_short_get(sql)

    maker_fee = float(results[0][0])
    taker_fee = float(results[0][1])

    # 面值
    parValue = config_contracts[contract_type]['parvalue']
    # 调整系数
    config_liquidation = config_liquidation[contract_type]

    sql = "SELECT swap_buy_volume,swap_buy_cost_open,swap_sell_volume,swap_sell_cost_open,swap_margin_balance,swap_profit_unreal,swap_buy_lever_rate,当前强平点 FROM information_client where name= '%s'  and contract = '%s' " % (
        client, contract)  # SQL 查询语句
    results = tools.mysql_short_get(sql)

    # 多方向持仓数量
    upPosition = float(results[0][0])
    # 多方向持仓均价
    upAveragePositionPrice = float(results[0][1])
    # 空方向持仓数量
    downPosition = float(results[0][2])
    # 空方向持仓均价
    downAveragePositionPrice = float(results[0][3])
    # 静态权益=账户权益-未实现盈亏
    margin_balance = float(results[0][4])
    profit_unreal = float(results[0][5])
    staticBalance = float(results[0][4]) - float(results[0][5])
    # 杠杆倍数
    multiple = float(results[0][6])
    liquidation_exchange = results[0][7]

    # 获取最新价格,保存为字典
    dict_price = tools.get_price_dict()
    price_latest = {'市价':dict_price[contract]['price_new'],'指数价':dict_price[contract]['price_index'],'标记价':dict_price[contract]['price_mark']}

    # 开始构件策略数据
    strategyList = []
    buyNumber = 0
    shortNumber = 0

    buy_max_volume = 0
    sell_max_volume = 0
    # {'id': '1', 'direction': '多', 'open': '53700', 'close': '54100', 'volume': '400', 'orderId': '1243143'},
    sql = "SELECT strategy_id,open,close,direction,volume,inposition,stop_profit,stop_loss,strategy_status,stop_profit_type,stop_loss_type FROM strategy_parameter_cycle_run where client_name='%s' and contract_type='%s' " % (client, contract)  # SQL 查询语句
    results = tools.mysql_short_get(sql)
    for result in results:
        temp_dict = {}
        temp_dict['id'] = result[0]
        temp_dict['open'] = result[1]
        temp_dict['close'] = result[2]
        temp_dict['direction'] = result[3]
        temp_dict['volume'] = result[4]
        temp_dict['inposition'] = result[5]
        temp_dict['stop_profit'] = result[6]
        temp_dict['stop_loss'] = result[7]
        temp_dict['strategy_status'] = result[8]
        temp_dict['stop_profit_type'] = result[9]
        temp_dict['stop_loss_type'] = result[10]

        temp_dict['orderId'] = '' if float(result[5]) == 0 else '1'
        if temp_dict['direction'] == '多':
            buyNumber += 1
            buy_max_volume = buy_max_volume + float(temp_dict['volume'])
        else:
            shortNumber += 1
            sell_max_volume = sell_max_volume + float(temp_dict['volume'])

        strategyList.append(temp_dict)

    # 开始处理web订单
    # 查非api委托
    sql = "SELECT price,volume,direction,offset,trade_volume,id FROM orders_active where client_name= '%s' and contract = '%s' and order_source != 'api' " % (client, contract)  # SQL 查询语句
    results = tools.mysql_short_get(sql)

    for result in results:
        price = result[0]
        volume = result[1]
        direction = result[2]
        offset = result[3]
        trade_volume = result[4]

        # 伪造策略信息
        def insert_list_strategy():
            strategyList.append({'id': '', 'open': temp_open, 'close': temp_close, 'inposition': temp_volume, 'volume': temp_volume, 'orderId': temp_orderId, 'direction': temp_direction, 'stop_profit': 'None', 'stop_loss': 'None', 'strategy_status': 'normal', 'stop_profit_type': '主动', 'stop_loss_type': '主动'})

        if direction == 'buy' and offset == 'open':
            temp_open = price
            temp_close = 1000000
            temp_volume = volume
            temp_direction = '多'
            temp_orderId = '' if offset == 'open' else '1'

            if temp_direction == '多':
                buyNumber += 1
                buy_max_volume = buy_max_volume + float(volume)
            else:
                shortNumber += 1
                sell_max_volume = sell_max_volume + float(volume)
            insert_list_strategy()

        elif direction == 'buy' and offset == 'close':
            temp_open = 100
            temp_close = price
            temp_volume = volume
            temp_direction = '多'
            temp_orderId = '' if offset == 'open' else '1'

            if temp_direction == '多':
                buyNumber += 1
                buy_max_volume = buy_max_volume + float(volume)
            else:
                shortNumber += 1
                sell_max_volume = sell_max_volume + float(volume)
            insert_list_strategy()

        elif direction == 'sell' and offset == 'open':
            temp_open = price
            temp_close = 100
            temp_volume = volume
            temp_direction = '空'
            temp_orderId = '' if offset == 'open' else '1'

            if temp_direction == '多':
                buyNumber += 1
                buy_max_volume = buy_max_volume + float(volume)
            else:
                shortNumber += 1
                sell_max_volume = sell_max_volume + float(volume)
            insert_list_strategy()

        elif direction == 'sell' and offset == 'close':
            temp_open = 1000000
            temp_close = price
            temp_volume = volume
            temp_direction = '空'
            temp_orderId = '' if offset == 'open' else '1'

            if temp_direction == '多':
                buyNumber += 1
                buy_max_volume = buy_max_volume + float(volume)
            else:
                shortNumber += 1
                sell_max_volume = sell_max_volume + float(volume)
            insert_list_strategy()

    # 修正上下终止影响
    # 获取数据
    sql = "SELECT 上终止,下终止 FROM information_client where name='%s' and contract='%s' " % (client, contract)  # SQL 查询语句
    results = tools.mysql_short_get(sql)
    end_up = results[0][0]
    end_down = results[0][1]
    # 消除上终止影响
    if end_up == 'None':
        pass
    else:
        end_up = float(end_up)
        for strategy in strategyList:
            if strategy['direction'] == '多':
                if strategy['stop_profit'] == 'None':
                    strategy['stop_profit'] = end_up
                else:
                    strategy['stop_profit'] = min([end_up, float(strategy['stop_profit'])])

            if strategy['direction'] == '空':
                if strategy['stop_loss'] == 'None':
                    strategy['stop_loss'] = end_up
                else:
                    strategy['stop_loss'] = min([end_up, float(strategy['stop_loss'])])

    if end_down == 'None':
        pass
    else:
        end_down = float(end_down)
        for strategy in strategyList:

            if strategy['direction'] == '多':
                if strategy['stop_loss'] == 'None':
                    strategy['stop_loss'] = end_down
                else:
                    strategy['stop_loss'] = max([end_down, float(strategy['stop_loss'])])

            if strategy['direction'] == '空':
                if strategy['stop_profit'] == 'None':
                    strategy['stop_profit'] = end_down
                else:
                    strategy['stop_profit'] = max([end_down, float(strategy['stop_profit'])])

    paramters = {
        'contract': contract,
        'price': price_latest,
        # 'contract_type': contract_type,
        'strategy_list': strategyList,
        'maker_fee': maker_fee,
        'taker_fee': taker_fee,
        'face_value': parValue,
        'leverage': multiple,
        'long_position': upPosition,
        'long_average_price': upAveragePositionPrice,
        'short_position': downPosition,
        'short_average_price': downAveragePositionPrice,
        'margin_balance': margin_balance,
        'static_balance': staticBalance,
        'profit_unreal': profit_unreal,
        'count_of_short_strategy': shortNumber,
        'count_of_long_strategy': buyNumber,
        'tick_size': 0.1**tools.get_contract_precision(contract),
        'config_liquidation': config_liquidation,
        'liquidation_exchange':liquidation_exchange
    }

    data_out = {'code': 1000, 'data': paramters, 'msg': '强平计算参数请求成功'}
    return respond(data_out)


if __name__ == '__main__':
    flask_port = 81
    app.run(host='0.0.0.0', port=flask_port, debug=False)

