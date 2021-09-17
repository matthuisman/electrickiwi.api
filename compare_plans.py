import arrow
from electrickiwi import ElectricKiwi

ek = ElectricKiwi()
token = ek.at_token()

loaded = False
try:
    with open('ek_creds.txt') as f:
        email = f.readline().strip()
        password = f.readline().strip()

    loaded = True
    print("Loaded Credentials: OK")
except:
    email = input('EK Email: ')
    password = ek.password_hash(input('EK Password: '))

customer = ek.login(email, password)
print('Logged in: OK')

if not loaded and input('Save credentials? Y/N : ').lower() in ('y', 'yes'):
    with open('ek_creds.txt', 'w') as f:
        f.write(email+'\n'+password)

connection = ek.connection_details()

include_discount = True
plans = {
    'loyal_kiwi': {
        'kwh_incl': 0.2852,
        'daily_incl': 0.83,
    },
    # 'loyal_kiwi_low': {
    #     'kwh_incl': 0.3072,
    #     'daily_incl': 0.3400,
    # },
    # 'kiwi': {
    #     'kwh_incl': 0.2963,
    #     'daily_incl': 0.8300,
    # },
    # 'kiwi_low': {
    #     'kwh_incl': 0.3183,
    #     'daily_incl': 0.3400,
    # },
    'stay_ahead': {
        'kwh_incl': 0.2362,
        'daily_incl': 1.35,
        'discount_percent': 11.5,
    },
    # 'stay_ahead_low': {
    #     'kwh_incl': 0.3204,
    #     'daily_incl': 0.3700,
    #     'discount_percent': 11.5,
    # },
    'move_master': {
        'kwh_incl': [['0700','0900',0.3959],['0900','1700',0.2613],['1700','2100',0.3959],['2100','2300',0.2613],['2300','0700',0.1980]],
        'daily_incl': 0.8300,
    },
    # 'move_master_low': {
    #     'kwh_incl': [['0700','0900',0.4265],['0900','1700',0.2814],['1700','2100',0.4265],['2100','2300',0.2814],['2300','0700',0.2132]],
    #     'daily_incl': 0.3400,
    # },
}

consumption = ek.consumption(arrow.now().shift(days=-2).shift(months=-12), arrow.now())

days = []
for date in consumption:
    data = consumption[date]
    hours = {}

    for interval in range(1, 24*2, 2):
        interval_data = data['intervals'][str(interval)]
        hour = int((((int(interval)-1)*30)/60)*100)
        hours[hour] = float(interval_data['consumption']) + float(data['intervals'][str(interval+1)]['consumption'])

    days.append(hours)

def get_price(hour, data):
    if type(data['kwh_incl']) is list:
        for entry in data['kwh_incl']:
            start = int(entry[0])
            end = int(entry[1])
            if end > start:
                if hour >= start and hour < end:
                    return entry[2]
            else:
                if (hour >= end and hour <= 2400) or (hour >= 0 and hour < end):
                    return entry[2]

        raise Exception('no price found!')
    else:
        return data['kwh_incl']

totals = []
total_kwh = 0.0
for name in plans:
    plan_total = 0.0
    data = plans[name]
    for day in days:
        daily_total = 0.0
        for hour in day:
            kwh = day[hour]
            total_kwh += kwh
            price = get_price(hour, data)
            daily_total += (kwh*price)

        daily_total += data['daily_incl']
        plan_total += daily_total
    
    if include_discount:
        discount = (data.get('discount_percent',0)/100)*plan_total
        plan_total -= discount

    totals.append([name, plan_total])

print(total_kwh)
totals = sorted(totals, key=lambda x: x[1])
for row in totals:
    print('{}: {}'.format(row[0], row[1]))
