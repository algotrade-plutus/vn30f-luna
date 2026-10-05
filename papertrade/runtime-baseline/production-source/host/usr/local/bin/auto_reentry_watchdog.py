#!/usr/bin/env python3
import time
import json
import logging
import subprocess
from datetime import datetime, timezone, timedelta

ICT = timezone(timedelta(hours=7))
LOG_FILE = '/var/log/auto_reentry_watchdog.log'
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

def log(msg: str):
    print(msg, flush=True)
    logging.info(msg)

def run_docker_py(script_content: str) -> str:
    # Write temp script and execute in container
    with open('/var/lib/algotrade/tmp_watchdog_cmd.py', 'w') as f:
        f.write(script_content)
    
    cmd = [
        'docker', 'run', '--rm',
        '--entrypoint', 'python3',
        '--env-file', '/run/algotrade/paperbroker.env',
        '--mount', 'type=bind,src=/var/lib/algotrade/runtime,dst=/app/runtime',
        '--mount', 'type=bind,src=/var/lib/algotrade/tmp_watchdog_cmd.py,dst=/app/tmp_watchdog_cmd.py',
        '943193395259.dkr.ecr.ap-southeast-1.amazonaws.com/algotrade-paper:v8-pg-spot-20260914',
        '/app/tmp_watchdog_cmd.py'
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip()

def get_broker_state():
    check_script = '''
import json
from algotrade_adapter import build_client
client = build_client(enable_fix=False)
port = client.get_portfolio_by_sub()
qty = 0
for it in port.get('items', []):
    sym = str(it.get('instrument') or it.get('symbol'))
    if 'VN30F2610' in sym:
        qty = int(float(it.get('quantity') or it.get('openQuantity') or 0))

orders = client.get_orders('2026-09-22', '2026-09-22').get('items', [])
open_orders = []
for o in orders:
    st = str(o.get('orderStatus') or o.get('statusCode') or '').upper()
    if st in ['0', 'NEW', 'CREATED', 'PARTIALLY_FILLED']:
        cl_id = o.get('clOrdId') or o.get('orderId')
        open_orders.append({
            'cl_ord_id': cl_id,
            'price': o.get('price'),
            'qty': o.get('orderQty') or o.get('quantity')
        })
print(json.dumps({'actual_qty': qty, 'open_orders': open_orders}))
'''
    out = run_docker_py(check_script)
    try:
        return json.loads(out)
    except Exception as e:
        log(f'Error parsing broker state: {e}, raw: {out}')
        return {'actual_qty': 0, 'open_orders': []}

def cancel_all_open_orders():
    cancel_script = '''
import sys, time
from algotrade_adapter import build_client
client = build_client(enable_fix=True, allow_orders=True)
client.connect()
if not client.wait_until_logged_on(timeout=15):
    print('FIX LOGIN FAILED:', client.last_logon_error())
    sys.exit(1)

orders = client.get_orders('2026-09-22', '2026-09-22').get('items', [])
cancelled = []
for o in orders:
    st = str(o.get('orderStatus') or o.get('statusCode') or '').upper()
    if st in ['0', 'NEW', 'CREATED', 'PARTIALLY_FILLED']:
        cl_id = o.get('clOrdId') or o.get('orderId')
        terminal, res_status = client.cancel_order(cl_id, timeout=3.0)
        cancelled.append((cl_id, terminal, res_status))

client.disconnect()
time.sleep(1)
print(f'CANCELLED_RESULTS: {cancelled}')
'''
    out = run_docker_py(cancel_script)
    log(f'Cancel output: {out}')

def start_algotrade_service():
    log('Starting systemctl start algotrade-paper...')
    subprocess.run(['systemctl', 'start', 'algotrade-paper'], check=True)
    time.sleep(5)
    st = subprocess.run(['systemctl', 'is-active', 'algotrade-paper'], capture_output=True, text=True).stdout.strip()
    log(f'algotrade-paper service status: {st}')

def main():
    log('=== AUTO RE-ENTRY WATCHDOG STARTED ===')
    
    while True:
        now_ict = datetime.now(ICT)
        now_time = now_ict.time()
        now_str = now_ict.strftime('%H:%M:%S')

        # Before 13:00 ICT (lunch break), sleep 60s
        if now_time < datetime.strptime('13:00:00', '%H:%M:%S').time():
            log(f'[{now_str}] Lunch break session. Sleeping 60s...')
            time.sleep(60)
            continue

        # Afternoon session (13:00 to 14:15):
        state = get_broker_state()
        actual_qty = state.get('actual_qty', 0)
        open_orders = state.get('open_orders', [])
        log(f'[{now_str}] Actual Qty: {actual_qty}, Open Orders: {len(open_orders)}')

        # If all 8 contracts filled at limit
        if actual_qty >= 8:
            log(f'[{now_str}] SUCCESS: All 8 contracts filled at limit prices! Starting bot to manage position.')
            start_algotrade_service()
            log('=== WATCHDOG COMPLETED SUCCESSFULLY ===')
            break

        # If reached 14:15 ICT and actual_qty < 8:
        if now_time >= datetime.strptime('14:15:00', '%H:%M:%S').time():
            log(f'[{now_str}] Reached 14:15 ICT cutoff. actual_qty={actual_qty} < 8. Activating Phase B...')
            
            # 1. Cancel open limits
            if open_orders:
                log(f'Cancelling {len(open_orders)} open limit orders...')
                cancel_all_open_orders()
            else:
                log('No open orders to cancel.')
            
            # 2. Wait until 14:20:00 ICT
            while True:
                current_ict = datetime.now(ICT)
                if current_ict.time() >= datetime.strptime('14:20:00', '%H:%M:%S').time():
                    break
                log(f'Waiting for 14:20:00 ICT (current: {current_ict.strftime("%H:%M:%S")})...')
                time.sleep(15)
            
            # 3. Start algotrade-paper at 14:20 ICT
            log(f'[{datetime.now(ICT).strftime("%H:%M:%S")}] Launching algotrade-paper for 14:24 decision window!')
            start_algotrade_service()
            log('=== WATCHDOG COMPLETED: algotrade-paper active for Phase B entry at 14:24 ===')
            break

        time.sleep(30)

if __name__ == '__main__':
    main()
