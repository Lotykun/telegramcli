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
import subprocess
from subprocess import Popen
from subprocess import PIPE
import signal
import db
import shlex
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.orm import relationship


class Update(db.Base):
    __tablename__ = 'update'

    id = Column(Integer, primary_key=True)
    update_number = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    active = Column(Boolean, nullable=False)

    def __init__(self, **kwargs):
        self.update_number = kwargs['num']
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.active = True

    def __repr__(self):
        return f'Update(update={self.update_number}, created_at={self.created_at}, ' \
               f'updated_at={self.created_at}, active={self.active})'

    def __str__(self):
        return self.updated_at.strftime("%Y-%m-%d %H:%M:%S") + ' ' + self.update_number
