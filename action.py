# This is a sample Python script.

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.
import json
from datetime import datetime
import time
import logging
import os
import yaml
import subprocess
from subprocess import Popen
from subprocess import PIPE
import signal
import db
import re
import paramiko
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean


class Action(db.Base):
    __tablename__ = 'action'
    STATUSES = {
        'init': 'INIT',
        'running': 'RUNNING',
        'aborted': 'ABORTED',
        'stopped': 'STOPPED',
        'finished': 'FINISHED',
    }

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    status = Column(String, nullable=False)
    extra_data = Column(String, nullable=True)

    def __init__(self, **kwargs):
        self.name = kwargs['config']['name']
        self.type = kwargs['config']['type']
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.status = self.STATUSES['init']
        self.config = kwargs['config']
        if 'extradata' in kwargs.keys():
            self.extra_data = kwargs['extradata']

    def __repr__(self):
        return f'Action(type={self.type}, created_at={self.created_at}, ' \
               f'updated_at={self.created_at}, config={self.config}, extra_data={self.extra_data})'

    def __str__(self):
        return self.updated_at.strftime("%Y-%m-%d %H:%M:%S") + ' ' + self.type + ' ' + self.status

    def allow_execute(self):
        result = {'response': True}
        same_action = db.session.query(Action).filter_by(name=self.name, type=self.type,
                                                         status=self.STATUSES['running']).first()
        if same_action is not None:
            result['response'] = False
            result['msg'] = 'There is one same running action, cant start another'
        return result

    def create_command(self):
        result = {'response': True, 'command': self.config['command']}
        for keyparam, param in self.config['params'].items():
            if 'value' in param.keys():
                result['command'] = result['command'].replace('{' + keyparam + '}', param['value'])
            else:
                if param['type'] == "datetime":
                    now = datetime.now()
                    result['command'] = result['command'].replace('{' + keyparam + '}', now.strftime("%Y%m%d%H%M%S"))
                elif param['type'] == "database":
                    parts = self.config['depends'].split(':')
                    depends_action = db.session.query(Action).filter_by(name=parts[1], type=parts[0],
                                                                        status=self.STATUSES['running']).first()
                    if depends_action is not None:
                        data = json.loads(depends_action.extra_data)
                        result['command'] = result['command'].replace('{' + keyparam + '}', str(data[keyparam]))
                    else:
                        result['response'] = False
                        result['msg'] = 'There is no depend script to this remote script'
        return result

    def save(self):
        self.updated_at = datetime.now()
        db.session.add(self)
        db.session.commit()
        return self

    def execute(self):
        pass


class ScriptAction(Action):
    def execute(self):
        result = {}
        logging.info('init script action: ' + self.name)
        result['response'] = False
        allow = self.allow_execute()
        if allow['response']:
            p = Popen(self.config['exec'], stdout=PIPE)
            while True:
                output = p.stdout.readline()
                if self.config['confirmed_run'] in output.strip().decode("utf-8"):
                    logging.info(output.strip())
                    self.status = self.STATUSES['running']
                    self.updated_at = datetime.now()
                    self.extra_data = json.dumps({'proc': p.pid})
                    db.session.add(self)
                    db.session.commit()
                    result['response'] = True
                    result['name'] = self.name
                    result['type'] = self.type
                    result['created'] = self.created_at
                    result['updated'] = self.updated_at
                    break
                if output:
                    logging.info(output.strip())
            logging.info('end script action')
        else:
            result['msg'] = allow['msg']
            self.status = self.STATUSES['stopped']
            self.updated_at = datetime.now()
            db.session.add(self)
            db.session.commit()
        return result


class SendSignalScriptAction(Action):
    def allow_execute(self):
        result = {'response': False}
        script_action = db.session.query(Action).filter_by(name="videoStartRecord",
                                                           type="script", status=self.STATUSES['running']).first()
        if script_action is not None:
            result['response'] = True
            result['script_action'] = script_action
        else:
            result['msg'] = 'There is no running script to send signal'
        return result

    def execute(self):
        result = {}
        logging.info('sending script signal: ' + self.config['signal'])
        result['response'] = False
        allow = self.allow_execute()
        if allow['response']:
            self.status = self.STATUSES['running']
            self.updated_at = datetime.now()
            db.session.add(self)
            db.session.commit()
            data = json.loads(allow['script_action'].extra_data)
            pid = data['proc']
            os.kill(pid, signal.SIGINT)
            allow['script_action'].status = self.STATUSES['finished']
            allow['script_action'].updated_at = datetime.now()
            db.session.add(allow['script_action'])
            db.session.commit()
            self.status = self.STATUSES['finished']
            self.updated_at = datetime.now()
            db.session.add(self)
            db.session.commit()
            result['response'] = True
            result['name'] = self.name
            result['type'] = self.type
            result['created'] = self.created_at
            result['updated'] = self.updated_at
            logging.info('script signal sent')
        else:
            result['msg'] = allow['msg']
            self.status = self.STATUSES['stopped']
            self.updated_at = datetime.now()
            db.session.add(self)
            db.session.commit()
        return result


class RemoteScriptAction(Action):
    def get_returned_data(self, out_script, command):
        result = {}
        for keyparam, param in self.config['returned_data'].items():
            if param['type'] == 'integer':
                result[keyparam] = int(re.search(keyparam + ": (\d*)", out_script).group(1)) + 1
        result['command'] = command
        result = json.dumps(result)
        return result

    def execute(self):
        result = {}
        logging.info('init script action: ' + self.name)
        result['response'] = False
        allow = self.allow_execute()
        if allow['response']:
            command_res = self.create_command()
            if command_res['response']:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(hostname=self.config['server'], username=self.config['user'],
                               password=self.config['password'])
                stdin, stdout, stderr = client.exec_command(command_res['command'])
                time.sleep(3)
                client.close()
                out = stdout.read().decode()
                if self.config['confirmed_run'] in out:
                    logging.info(out)
                    self.status = self.STATUSES['running']
                    self.extra_data = self.get_returned_data(out, command_res['command'])
                    result['response'] = True
                    result['name'] = self.name
                    result['type'] = self.type
                    result['created'] = self.created_at
                    result['updated'] = self.updated_at
                else:
                    result['msg'] = 'undetermined error'
                    self.status = self.STATUSES['stopped']
            else:
                result['msg'] = command_res['msg']
                self.status = self.STATUSES['stopped']
            logging.info('end script action')
        else:
            result['msg'] = allow['msg']
            self.status = self.STATUSES['stopped']
        self.save()
        return result


class SendSignalRemoteScriptAction(RemoteScriptAction):
    def allow_execute(self):
        result = {'response': False}
        parts = self.config['depends'].split(':')
        depends_action = db.session.query(Action).filter_by(name=parts[1], type=parts[0],
                                                            status=self.STATUSES['running']).first()
        if depends_action is not None:
            result['response'] = True
            result['script_action'] = depends_action
        else:
            result['msg'] = 'There is no running script to send signal'
        return result

    def get_returned_data(self, out_script, command):
        result = {}
        for keyparam, param in self.config['returned_data'].items():
            if param['type'] == 'integer':
                result[keyparam] = int(re.search(keyparam + ": (\d*)", out_script).group(1))
        result['command'] = command
        result = json.dumps(result)
        return result

    def execute(self):
        result = {}
        logging.info('init script action: ' + self.name)
        result['response'] = False
        allow = self.allow_execute()
        if allow['response']:
            command_res = self.create_command()
            if command_res['response']:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(hostname=self.config['server'], username=self.config['user'],
                               password=self.config['password'])
                stdin, stdout, stderr = client.exec_command(command_res['command'])
                time.sleep(3)
                client.close()
                out = stdout.read().decode()
                if self.config['confirmed_run'] in out:
                    logging.info(out)
                    self.status = self.STATUSES['running']
                    self.extra_data = self.get_returned_data(out, command_res['command'])

                    allow['script_action'].status = self.STATUSES['finished']
                    allow['script_action'].save()

                    self.status = self.STATUSES['finished']
                    result['response'] = True
                    result['name'] = self.name
                    result['type'] = self.type
                    result['created'] = self.created_at
                    result['updated'] = self.updated_at
                else:
                    result['msg'] = 'undetermined error'
                    self.status = self.STATUSES['stopped']
            else:
                result['msg'] = command_res['msg']
                self.status = self.STATUSES['stopped']
            logging.info('end script action')
        else:
            result['msg'] = allow['msg']
            self.status = self.STATUSES['stopped']
        self.save()
        return result
