# This is a sample Python script.

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.
import requests
import json
from datetime import datetime
import time
import logging
import argparse
import os
import yaml
import sys
import db
import subprocess
from subprocess import Popen
from subprocess import PIPE
import signal
import re
import shlex
from action import Action
from action import SendSignalScriptAction
from update import Update


def get_project_path():
    return os.path.dirname(os.path.abspath(__file__))


def get_config():
    config_file = get_project_path() + "/config/config_" + args.environment + ".yml"
    with open(config_file) as f:
        data = yaml.load(f, Loader=yaml.FullLoader)
    return data


def get_class(kls):
    parts = kls.split('.')
    module = ".".join(parts[:-1])
    m = __import__(module)
    for comp in parts[1:]:
        m = getattr(m, comp)
    return m


def parse_arguments():
    # Create argument parser
    parser = argparse.ArgumentParser()

    # Positional mandatory arguments
    parser.add_argument("-env", "--environment", choices=['dev', 'sta', 'prod'],
                        help="modo de donde esta el navegador a usar y el entorno a usar", type=str)

    # Print version
    parser.add_argument("--version", action="version", version='%(prog)s - Version 1.0')

    # Parse arguments
    data = parser.parse_args()
    return data


def init_log_file(filename):
    log_file_path = get_project_path() + '/log/'
    log_file_name = filename + '_main.log'
    logging.basicConfig(
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S',
        format='%(asctime)s|%(levelname)-8s|%(message)s',
        handlers=[
            logging.FileHandler(log_file_path + log_file_name),
            logging.StreamHandler()
        ]
    )


def send_message(text):
    url = host + token + '/sendMessage'
    logging.debug('Request: ' + url)
    data = {'chat_id': chat, 'text': text}
    req = requests.post(url, data=data)
    logging.debug('Response: ' + str(req.content))
    content = json.loads(req.content)
    if content['ok']:
        if len(content['result']) > 0:
            logging.info('Telegram message sent')
        else:
            logging.error('Nothing in sending message, weird')
    else:
        logging.error('Content is not ok something wrong sending message')


def send_file(file):
    filename, file_extension = os.path.splitext(file)
    filename = os.path.basename(file)
    file_type = ''
    if file_extension in ['.mp4', '.avi']:
        file_type = 'video'
    url = host + token + '/send' + file_type[0].upper() + file_type[1:]
    logging.debug('Request: ' + url)
    data = {'chat_id': chat}

    files = [(file_type, (filename, open(file, 'rb'), 'application/octet-stream'))]
    req = requests.post(url, data=data, files=files)
    logging.info('Response: ' + str(req.content))
    content = json.loads(req.content)
    if content['ok']:
        if len(content['result']) > 0:
            logging.info('Telegram message sent')
        else:
            logging.error('Nothing in sending message, weird')
    else:
        logging.error('Content is not ok something wrong sending message')


def receive_message(update=None):
    url = host + token + '/getUpdates'
    logging.debug('Request: ' + url)
    x = requests.get(url)
    logging.debug('Response: ' + str(x.content))
    content = json.loads(x.content)
    result = {}
    if content['ok']:
        if len(content['result']) > 0:
            last_update = content['result'][-1]
            if last_update['update_id'] != update:
                id_message = last_update['message']['message_id']
                from_message = last_update['message']['from']['first_name']
                chat_message = last_update['message']['chat']['id']
                date_message = datetime.fromtimestamp(last_update['message']['date'])
                text_message = last_update['message']['text']
                result['response'] = True
                result['msg_id'] = id_message
                result['msg'] = text_message
                result['msg_formatted'] = date_message.strftime("%Y-%m-%d %H:%M:%S") + ' FROM: ' \
                                          + from_message + ' CHAT: ' + str(chat_message) + ' TEXT: ' + text_message
                result['update'] = last_update['update_id']
            else:
                result['response'] = False
        else:
            result['response'] = False
            result['msg'] = 'Nothing updates, weird'
    else:
        result['response'] = False
        result['msg'] = 'content is not ok algo pasa'
    return result


def get_current_update():
    update = db.session.query(Update).filter_by(active=True).first()
    return update


def format_message(msg):
    result = {}
    if 'grabar' in msg:
        if 'start' in msg:
            result['action_name'] = 'videoStartRecord'
            result['action_params'] = {}
        elif 'stop' in msg:
            result['action_name'] = 'videoStopRecord'
            result['action_params'] = {}
    elif 'get' in msg:
        if 'file' in msg:
            if 'remote' in msg:
                result['action_name'] = 'getVideoRecord'
                name = re.search("name:(.*)", msg).group(1)
                result['action_params'] = {'filename': name}

    return result


def process_action(msg):
    action_config = config['parameters']['actions'][msg['action_name']]
    action_config['name'] = msg['action_name']
    action_class_name = action_config['type'][0].upper() + action_config['type'][1:] + 'Action'
    action_class = get_class('action.' + action_class_name)
    try:
        action = action_class(config=action_config, extradata=msg['action_params'])
        action.save()
        action_response = action.execute()
        if action_response['response']:
            telegram_msg = action_response['msg']
        else:
            telegram_msg = action_response['err_msg']
        if 'file' in action_response.keys():
            send_file(action_response['file'])
            os.remove(action_response['file'])
        send_message(telegram_msg)
    except Exception as err:
        ex_type = type(err).__name__
        ex_message = str(err)
        err_message = 'Exception: ' + str(ex_type) + ' Message: ' + ex_message
        logging.error(err_message)
        ext_data = {'msg': action_config['name'] + ' ' + action_config['type'] + ' Failed:' + err_message}
        action.status = action.STATUSES['stopped']
        action.extra_data = json.dumps(ext_data)
        action.save()
        send_message(action_config['name'] + ' ' + action_config['type'] + ' Failed:' + err_message)
        return False
    return True


def signal_handler(sig, frame):
    logging.info('END TELEGRAM CLI: Args: ' + str(args))
    send_message('Adios Loty!.. Hasta La Proxima')
    sys.exit(0)


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    args = parse_arguments()
    config = get_config()
    host = config['parameters']['host']
    token = config['parameters']['token']
    chat = config['parameters']['chat_id']
    now = datetime.now()
    file_name = now.strftime("%Y%m%d%H%M%S")
    init_log_file(filename=file_name)
    current_update = get_current_update()
    if current_update:
        current_update_number = current_update.update_number
    else:
        current_update_number = 0
        current_update = Update(num=current_update_number)
    logging.info('INIT TELEGRAM CLI: Args: ' + str(args))
    send_message('Hola Loty! Te escucho...')
    action_history = []
    while True:
        res = receive_message(current_update_number)
        if res['response']:
            current_update.active = False
            db.session.add(current_update)
            db.session.commit()
            logging.info('MESSAGE: ' + res['msg_formatted'])
            message = format_message(res['msg'])
            ac = process_action(message)
            current_update_number = res['update']
            new_update = Update(num=current_update_number)
            db.session.add(new_update)
            db.session.commit()
            current_update = new_update
        else:
            if 'msg' in res.keys():
                logging.error(res['msg'])
                break
        time.sleep(3)
    signal.pause()

