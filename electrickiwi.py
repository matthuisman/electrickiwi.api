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
        params = params or {}

        headers = {
            'x-client': 'ek-app', 
            'x-apiversion': '1_0',
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