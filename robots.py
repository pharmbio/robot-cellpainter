from __future__ import annotations
from dataclasses import *
from typing import *

from datetime import datetime, timedelta
from urllib.request import urlopen

import abc
import json
import os
import re
import socket
import time

from moves import movelists
from robotarm import Robotarm
import utils
from utils import Mutable

@dataclass(frozen=True)
class Env:
    robotarm_host: str
    robotarm_port: int

    incu_url: str
    biotek_url: str

ENV = Env(
    # Use start-proxies.sh to forward robot to localhost
    robotarm_host = os.environ.get('ROBOT_IP', 'localhost'),
    robotarm_port = 30001,
    incu_url = os.environ.get('INCU_URL', '?'),
    biotek_url = os.environ.get('BIOTEK_URL', '?'),
)

@dataclass(frozen=True)
class Config:
    time_mode:          Literal['wall', 'fast forward',                  ]
    disp_and_wash_mode: Literal['noop', 'execute', 'execute short',      ]
    incu_mode:          Literal['noop', 'execute',                       ]
    robotarm_mode:      Literal['noop', 'execute', 'execute no gripper', ]
    timers: dict[str, datetime] = field(default_factory=dict)
    skipped_time: Mutable[float] = Mutable.factory(0.0)
    def name(self) -> str:
        for k, v in configs.items():
            if v is self:
                return k
        raise ValueError(f'unknown config {self}')

configs: dict[str, Config]
configs = {
    'live':          Config('wall',         'execute',       'execute', 'execute'),
    'test-all':      Config('fast forward', 'execute short', 'execute', 'execute'),
    'test-arm-incu': Config('fast forward', 'noop',          'execute', 'execute'),
    'simulator':     Config('fast forward', 'noop',          'noop',    'execute no gripper'),
    'dry-run':       Config('fast forward', 'noop',          'noop',    'noop'),
}

class Time:
    @staticmethod
    def now(config: Config) -> datetime:
        if config.time_mode == 'wall':
            assert config.skipped_time.value == 0.0
        return datetime.now() + timedelta(seconds=config.skipped_time.value)

    @staticmethod
    def sleep(secs: float, config: Config):
        if secs < 0:
            print('Behind time:', -secs, 'seconds!')
            return
        if config.time_mode == 'wall':
            print('Sleeping for', secs, 'seconds...')
            time.sleep(secs)
        else:
            print('Fast-forwarding', secs, 'seconds...')
            config.skipped_time.value += secs

def curl(url: str) -> Any:
    print('curl', url)
    ten_minutes = 60 * 10
    return json.loads(urlopen(url, timeout=ten_minutes).read())

import threading
def spawn(f: Callable[[], None]) -> None:
    threading.Thread(target=f, daemon=True).start()

from queue import SimpleQueue

@dataclass(frozen=True)
class Message:
    path: str
    config: Config
    on_finished: Callable[[], None] | None = None

@dataclass
class Biotek:
    name: str
    queue: SimpleQueue[Message] = field(default_factory=SimpleQueue)
    state: Literal['ready', 'busy'] = 'ready'
    last_started: datetime | None = None
    last_finished: datetime | None = None

    def __post_init__(self):
        t = threading.Thread(target=self.loop, daemon=True)
        t.start()

    def loop(self):
        r'''
        Repeatedly try to run the protocol until it succeeds or we get an unknown error.

        Success looks like this:

            {"err":"","out":{"details":"1 - eOK","status":"1","value":""}}

            {"err":"","out":{"details": "1 - eReady - the run completed
            successfully: stop polling for status", "status":"1", "value":""}}

        Acceptable failure looks like this:

            {"err":"","out":{"details":"Message - Exception calling cLHC method:
                LHC_TestCommunications, ErrorCode: 24673, ErrorString:
                Error code: 6061rnPort is no longer available - ...",
            "status":"99","value":"EXCEPTION"}}

        '''
        while msg := self.queue.get():
            self.state = 'busy'
            while True:
                self.last_started = Time.now(msg.config)
                res = curl(ENV.biotek_url + '/' + self.name + '/LHC_RunProtocol/' + msg.path)
                out = res['out']
                status = out['status']
                details = out['details']
                if status == '99' and 'Error code: 6061' in details and 'Port is no longer available' in details:
                    print(self.name, 'got error code 6061, retrying...')
                    continue
                elif status == '1' and ('eOK' in details or 'eReady' in details):
                    break
                else:
                    raise ValueError(res)
            self.last_finished = Time.now(msg.config)
            if msg.on_finished:
                msg.on_finished()
            self.state = 'ready'

    def is_ready(self):
        return self.state == 'ready'

    def run(self, path: str, config: Config, on_finished: Callable[[], None] | None = None):
        assert self.is_ready()
        self.state = 'busy'
        self.queue.put_nowait(Message(path, config, on_finished))

wash = Biotek('wash')
disp = Biotek('disp')

class Command(abc.ABC):
    @abc.abstractmethod
    def execute(self, config: Config) -> None:
        pass

class Waitable(abc.ABC):
    pass

@dataclass(frozen=True)
class DispFinished(Waitable):
    plate_id: str

@dataclass(frozen=True)
class WashStarted(Waitable):
    pass

@dataclass(frozen=True)
class Now(Waitable):
    pass

@dataclass(frozen=True)
class Ready(Waitable):
    name: Literal['incu', 'wash', 'disp']
    def wait(self, config: Config):
        if self.name == 'wash':
            while not wash.is_ready():
                time.sleep(0.01)
        elif self.name == 'disp':
            while not disp.is_ready():
                time.sleep(0.01)
        elif self.name == 'incu':
            while not is_incu_ready(config):
                time.sleep(0.01)
        else:
            raise ValueError(self.name)

@dataclass(frozen=True)
class wait_for(Command):
    base: Waitable
    plus_seconds: int = 0

    def execute(self, config: Config) -> None:
        if isinstance(self.base, Ready):
            self.base.wait(config)
            assert self.plus_seconds == 0
        elif isinstance(self.base, WashStarted):
            assert wash.last_started is not None
            d = datetime.now() - wash.last_started + timedelta(seconds=self.plus_seconds)
            time.sleep(d.total_seconds())
        elif isinstance(self.base, DispFinished):
            fin = config.timers[self.base.plate_id]
            d = datetime.now() - fin + timedelta(seconds=self.plus_seconds)
            time.sleep(d.total_seconds())
        elif isinstance(self.base, Now):
            time.sleep(self.plus_seconds)
        else:
            raise ValueError

    def __add__(self, other: int) -> wait_for:
        return wait_for(self.base, self.plus_seconds + other)

def get_robotarm(config: Config, quiet: bool = False) -> Robotarm:
    if config.robotarm_mode == 'noop':
        return Robotarm.init_simulate(with_gripper=True, quiet=quiet)
    assert config.robotarm_mode == 'execute' or config.robotarm_mode == 'execute no gripper'
    with_gripper = config.robotarm_mode == 'execute'
    return Robotarm.init(ENV.robotarm_host, ENV.robotarm_port, with_gripper, quiet=quiet)

@dataclass(frozen=True)
class robotarm_cmd(Command):
    program_name: str

    def execute(self, config: Config) -> None:
        arm = get_robotarm(config)
        arm.execute_moves(movelists[self.program_name], name=self.program_name)
        arm.close()

@dataclass(frozen=True)
class wash_cmd(Command):
    protocol_path: str

    def execute(self, config: Config) -> None:
        if config.disp_and_wash_mode == 'noop':
            return
        elif config.disp_and_wash_mode == 'execute short':
            wash.run('automation/2_4_6_W-3X_FinalAspirate_test.LHC', config)
        elif config.disp_and_wash_mode == 'execute':
            wash.run(self.protocol_path, config)
        else:
            raise ValueError

@dataclass(frozen=True)
class disp_cmd(Command):
    protocol_path: str
    plate_id: str | None = None
    def execute(self, config: Config) -> None:
        if config.disp_and_wash_mode == 'noop':
            return
        elif config.disp_and_wash_mode == 'execute' or config.disp_and_wash_mode == 'execute short':
            if self.plate_id:
                plate_id = self.plate_id
                cb = lambda: config.timers.__setitem__(plate_id, datetime.now())
            else:
                cb = None
            disp.run(self.protocol_path, config, cb)
        else:
            raise ValueError

@dataclass(frozen=True)
class incu_cmd(Command):
    action: Literal['put', 'get']
    incu_loc: str
    def execute(self, config: Config) -> None:
        assert self.action in 'put get'.split()
        if config.incu_mode == 'noop':
            # print('dry run', self)
            return
        elif config.incu_mode == 'execute':
            if self.action == 'put':
                action_path = 'input_plate'
            elif self.action == 'get':
                action_path = 'output_plate'
            else:
                raise ValueError
            url = ENV.incu_url + '/' + action_path + '/' + self.incu_loc
            res = curl(url)
            assert res['status'] == 'OK', f'status not OK: {res = }'
        else:
            raise ValueError

def is_incu_ready(config: Config) -> bool:
    res = curl(ENV.incu_url + '/is_ready')
    assert res['status'] == 'OK', f'status not OK: {res = }'
    return res['value'] is True

@dataclass(frozen=True)
class par(Command):
    subs: list[wash_cmd | disp_cmd | incu_cmd | robotarm_cmd]

    def __post_init__(self):
        for cmd, next in utils.iterate_with_next(self.subs):
            if isinstance(cmd, robotarm_cmd):
                assert next is None, 'put the nonblocking commands first, then the robotarm last'

    def sub_cmds(self) -> tuple[Command, ...]:
        return tuple(self.subs)

    def execute(self, config: Config) -> None:
        for sub in self.sub_cmds():
            sub.execute(config)
