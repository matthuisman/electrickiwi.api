import requests
import random
import time
import arrow

from hashlib import md5
from decimal import Decimal

from cryptoJS import encrypt

class Hour(object):
    def __init__(self, interval, start, end, hop_allow=0):
        self.interval  = int(interval)
        self.start     = arrow.get(start, 'h:mm A')
        self.end       = arrow.get(end, 'h:mm A')
        self.hop_allow = bool(int(hop_allow))

    def __repr__(self):
        return '{} ({} - {})'.format(self.interval, self.start.format('h:mm A'), self.end.format('h:mm A'))

    def __eq__(self, other):
        return self.interval == other.interval

    def __ne__(self, other):
        return self.interval != other.interval

    def __gt__(self, other):
        return self.interval > other.interval

    def __le__(self, other):
        return self.interval <= other.interval

class ElectricException(Exception):
    pass

class ElectricKiwi(object):
    _secret          = None
    _secret_position = None
    _sid             = None
    _customer        = None

    def __init__(self, at_token=None):
        if at_token:
            self.at_token(at_token)

    def login(self, email, password_hash, customer_index=0):
        payload = {
            'email'   : email,
            'password': password_hash,
        }

        data = self.request('/login/', payload, type='POST')

        self._sid      = data['sid']
        self._customer = data['customer'][customer_index]

        return self._customer

    def password_hash(self, password):
        return md5(password.encode('utf-8')).hexdigest()

    def at_token(self, at_token=None):
        if not at_token:
            data = self.request('/at/')
            at_token = data['token']
            
        self._secret          = at_token[2:-2]
        self._secret_position = int(at_token[:2])

        return at_token

    def request(self, endpoint, params=None, type='GET'):
        headers = {
            'x-client': 'ek-app', 
            'x-apiversion': '2_2',
            'origin': 'http://localhost',
            'referer': 'http://localhost',
            'accept': 'application/json, text/plain, */*',
            'user-agent': 'Mozilla/5.0 (Linux; Android 11; Mi 5 Build/RQ3A.211001.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/96.0.4664.104 Mobile Safari/537.36',
            'x-requested-with': 'nz.co.electrickiwi.mobile.app',
        }

        if self._secret:
            headers['x-token'] = self._get_token(endpoint)

        if self._sid:
            headers['x-sid'] = self._sid

        data = requests.request(type, 'https://api.electrickiwi.co.nz{}'.format(endpoint), headers=headers, json=params).json()
        if 'error' in data:
            raise ElectricException(data['error']['detail'])

        return data['data']

    def _get_token(self, endpoint):
        length = random.randint(10, len(self._secret) - 2)
        secret = self._secret[:length]

        data = endpoint + '|' + str(int(time.time())+30) + '|' + ''.join(random.choice('0123456789ABCDEF') for i in range(16))
        encrypted = encrypt(data.encode(), secret.encode()).decode()

        return encrypted[:self._secret_position] + str(length) + encrypted[self._secret_position:]

    def get_hours(self, hop_only=False):
        data = self.request('/hop/')

        hours = {}
        for interval in sorted(data['intervals'].keys(), key=lambda x: int(x)):
            row = data['intervals'][interval]

            if hop_only and not row['active']:
                continue

            hour = Hour(interval, row['start_time'], row['end_time'], row['active'])
            hours[hour.interval] = hour

        return hours

    def _require_login(self):
        if not self._sid:
            raise ElectricException('You need to login first')

    def consumption(self, start_date=None, end_date=None):
        self._require_login()

        start_date = start_date or arrow.now().shift(days=-9)
        end_date   = end_date   or start_date.shift(days=7)

        data = self.request('/consumption/averages/{customer_id}/{connection_id}/?start_date={start_date}&end_date={end_date}&group_by=day'
                .format(customer_id=self._customer['id'], connection_id=self._customer['connection']['id'], start_date=start_date.format('YYYY-MM-DD'), end_date=end_date.format('YYYY-MM-DD')))

        return data['usage']

    def running_balance(self):
        self._require_login()

        data = self.request('/account/running_balance/{customer_id}/'.format(customer_id=self._customer['id']))
        return data

    def connection_details(self):
        self._require_login()

        data = self.request('/connection/details/{customer_id}/{connection_id}/'.format(customer_id=self._customer['id'], connection_id=self._customer['connection']['id']))
        return data
    
    def get_hop_hour(self):
        self._require_login()

        data = self.request('/hop/{customer_id}/{connection_id}/'.format(customer_id=self._customer['id'], connection_id=self._customer['connection']['id']))
        return Hour(data['start']['interval'], data['start']['start_time'], data['end']['end_time'], 1)

    def set_hop_hour(self, hour):
        self._require_login()
        interval = hour.interval if type(hour) == Hour else int(hour)
        data = self.request('/hop/{customer_id}/{connection_id}/'.format(customer_id=self._customer['id'], connection_id=self._customer['connection']['id']), params={'start': interval}, type='POST')
        return Hour(data['start']['interval'], data['start']['start_time'], data['end']['end_time'], 1)

def hop_score():
    ek       = ElectricKiwi()
    token    = ek.at_token()

    loaded = False
    try:
        with open('ek_creds.txt') as f:
            email    = f.readline().strip()
            password = f.readline().strip()

        loaded = True
        print("Loaded Credentials: OK")
    except:
        email    = input('EK Email: ')
        password = ek.password_hash(input('EK Password: '))
    
    customer = ek.login(email, password)
    print('Logged in: OK')

    if not loaded and input('Save credentials? Y/N : ').lower() in ('y', 'yes'):
        with open('ek_creds.txt', 'w') as f:
            f.write(email+'\n'+password)

    connection  = ek.connection_details()

    kwh_cost    = Decimal(connection['pricing_plan']['usage_rate_inc_gst'])
    wrong_kwh   = Decimal('0.0')
    hop_savings = Decimal('0.0')

    print("")
    consumption = ek.consumption(arrow.now().shift(days=-2).shift(months=-1), arrow.now())
    for date in consumption:
        data = consumption[date]

        hop_usage = Decimal(data['consumption_adjustment'])
        hop_savings += hop_usage

        for interval in range(1, 24*2):
            interval_data = data['intervals'][str(interval)]
            if interval_data['hop_best']:
                hop_best = Decimal(interval_data['consumption']) + Decimal(data['intervals'][str(interval+1)]['consumption'])
                break

        date = arrow.get(date, 'YYYY-MM-DD').format('DD/MM/YYYY')

        diff = hop_best - hop_usage
        if diff > 0.01:
            wrong_kwh += diff
            print('{} - Wrong HOP: {}kWh vs {}kWh ({}kWh)'.format(date, hop_best, hop_usage, diff))
        else:
            print('{} - Correct HOP: {}kWh'.format(date, hop_usage))

    print('\nHOP Savings: {}kWh (${:.2f})'.format(hop_savings, hop_savings * kwh_cost))
    print('Missed HOP: {}kWh (${:.2f})'.format(wrong_kwh, wrong_kwh * kwh_cost))
    print('HOP Score: {:.2f}%'.format(Decimal(100.0) - ((wrong_kwh / hop_savings) * 100)))

if __name__ == '__main__':
    try:
        hop_score()
    except Exception as e:
        print(e)

    input('\nPress any key to exit')


# login: { key: 'login', endpoint: '/login/', method: 'post' },
# logout: { key: 'logout', endpoint: '/logout/{customerId}/', method: 'post' },
# connection_details: { key: 'connection_details', endpoint: '/connection/details/{customerId}/{connectionId}/', method: 'get' },
# hop: { key: 'hop', endpoint: '/hop/', method: 'get', preload: true },
# hop_customerid: { key: 'hop_customerid', endpoint: '/hop/{customerId}/', method: 'get' },
# hop_customerid_connectionid: { key: 'hop_customerid_connectionid', endpoint: '/hop/{customerId}/{connectionId}/', method: 'get', preload: true },
# update_hop_customerid_connectionid: { key: 'update_hop_customerid_connectionid', endpoint: '/hop/{customerId}/{connectionId}/', method: 'post' },
# lang: { key: 'lang', endpoint: '/language/{lang}/', method: 'get' },
# language: { key: 'language', endpoint: '/service/language/', method: 'get' },
# get_bill_alert: { key: 'get_bill_alert', endpoint: '/subscription/bill_alert/{customerId}/{connectionId}/', method: 'get' },
# forgot_password: { key: 'forgot_password', endpoint: '/password/forgot/', method: 'post' },
# key_submission: { key: 'key_submission', endpoint: '/password/forgot/otp/', method: 'post' },
# update_password: { key: 'update_password', endpoint: '/password/forgot/{respartnerId}/{otp}/', method: 'post' },
# update_bill_alert: { key: 'update_bill_alert', endpoint: '/subscription/bill_alert/{customerId}/{connectionId}/', method: 'post' },
# unsubscribe_bill_alert: { key: 'unsubscribe_bill_alert', endpoint: '/subscription/bill_alert/unsubscribe/{customerId}/{connectionId}/', method: 'get' },
# get_customer_bills: { key: 'get_customer_bills', endpoint: '/billing/bills/{customerId}/', method: 'get' },
# get_your_details: { key: 'get_your_details', endpoint: '/customer/{customerId}/', method: 'get', preload: true },
# post_your_details: { key: 'post_your_details', endpoint: '/customer/{customerId}/', method: 'post' },
# get_message_details: { key: 'get_message_details', endpoint: '/messaging/message/{customerId}/{messageId}/', method: 'get' },
# get_messages: { key: 'get_messages', endpoint: '/messaging/messages/{customerId}/', method: 'get' },
# post_messages: { key: 'post_messages', endpoint: '/messaging/messages/{customerId}/', method: 'post' },
# get_billing_details: { key: 'get_billing_details', endpoint: '/billing/details/{customerId}/', method: 'get', preload: true },
# account_payment_url: { key: 'account_payment_url', endpoint: '/payment/url/{customerId}/', method: 'post' },
# get_billing_frequency: { key: 'get_billing_frequency', endpoint: '/billing/frequency/{customerId}/', method: 'get', preload: true },
# update_billing_frequency: { key: 'update_billing_frequency', endpoint: '/billing/frequency/{customerId}/', method: 'post' },
# account_running_balance: { key: 'account_running_balance', endpoint: '/account/running_balance/{customerId}/', method: 'get' },
# account_status: { key: 'account_status', endpoint: '/account/status/{customerId}/', method: 'get', preload: true },
# get_connection_details: { key: 'get_connection_details', endpoint: '/connection/details/{customerId}/{connectionId}/', method: 'get' },
# move_connection: { key: 'move_connection', endpoint: '/connection/move/{customerId}/', method: 'post' },
# moving_house_config: { key: 'moving_house_config', endpoint: '/service/moving_house/config/', method: 'get' },
# get_stay_ahead: { key: 'get_stay_ahead', endpoint: '/subscription/stay_ahead/{customerId}/', method: 'get', preload: true },
# update_stay_ahead: { key: 'update_stay_ahead', endpoint: '/subscription/stay_ahead/{customerId}/', method: 'post' },
# unsubscribe_stay_ahead: { key: 'unsubscribe_stay_ahead', endpoint: '/subscription/stay_ahead/unsubscribe/{customerId}/', method: 'get' },
# get_consumption_summary: { key: 'get_consumption_summary', endpoint: '/consumption/summary/{customerId}/{connectionId}/', method: 'get' },
# get_consumption: { key: 'get_consumption', endpoint: '/consumption/{customerId}/{connectionId}/', method: 'get' },
# outage_contact_details: { key: 'outageContact_details', endpoint: '/service/outage/contact/{connectionId}/', method: 'get' },
# refer_a_friend: { key: 'refer_a_friend', endpoint: '/refer_a_friend/{customerId}/', method: 'get' },
# get_savings: { key: 'get_savings', endpoint: '/savings/{customerId}/', method: 'get' },
# get_credits: { key: 'get_credits', endpoint: '/credits/{customerId}/', method: 'get' },
# get_replies: { key: 'get_replies', endpoint: '/messaging/replies/{customerId}/{messageId}/', method: 'get' },
# get_product_notifications: { key: 'get_product_notifications', endpoint: '/notifications/{customerId}/', method: 'get' },
# get_product_notification_details: { key: 'get_product_notification_details', endpoint: '/notification/{customerId}/{notificationProductId}/', method: 'get' },
# update_product_notifications: { key: 'update_product_notifications', endpoint: '/notification/{customerId}/{notificationProductId}/', method: 'post' },
# update_device_details: { key: 'update_device_details', endpoint: '/device/register/{customerId}/', method: 'post' },
# email_checker: { key: 'email_checker', endpoint: '/service/email_checker/', method: 'post' },
# products: { key: 'products', endpoint: '/service/products/', method: 'get' },
# client_config: { key: 'client_config', endpoint: '/service/client/config/', method: 'get' },
# consumption_averages: { key: 'consumption_averages', endpoint: '/consumption/averages/{customerId}/{connectionId}/', method: 'get' },
# contact_reasons: { key: 'contact_reasons', endpoint: '/service/contact_reasons/', method: 'get' },