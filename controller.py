from __future__ import annotations

from dataclasses import dataclass, field, replace, astuple
from utils import dotdict
from typing import Dict, Any, Tuple, Literal, NewType, Iterator
import datetime

from utils import show
import snoop # type: ignore
snoop.install(pformat=show)
pp: Any


JobId = NewType('JobId', str)

@dataclass(frozen=True)
class UnresolvedTime:
    time: str
    id: JobId | None = None # first wait for this machine

@dataclass(frozen=True)
class Plate:
    id: str
    loc: str
    lid_loc: str = 'self'
    target_loc: None | str = None
    queue: list[ProtocolStep] = field(default_factory=list, repr=False)
    waiting_for: None | JobId | datetime.datetime | UnresolvedTime = None
    meta: Any = field(default=None, repr=False)

    def top(self) -> ProtocolStep:
        return self.queue[0]

    def pop(self) -> Plate:
        return replace(self, queue=self.queue[1:])

H = [21, 19, 17, 15, 13, 11, 9, 7, 5, 3, 1]
I = [i+1 for i in range(42)]
Out = [18] # [ i+1 for i in range(18) ] # todo: measure out_hotel_dist
Out = [ i+1 for i in range(18) ] # todo: measure out_hotel_dist

if 0:
    # small test version
    H = [21, 19, 17, 15, 13]
    I = [1, 2, 3, 4, 5]
    Out = [18]

h21 = 'h21'

incu_locs: list[str] = [f'i{i}' for i in I]
h_locs:    list[str] = [f'h{i}' for i in H]
r_locs:    list[str] = [f'r{i}' for i in H]
out_locs:  list[str] = [f'out{i}' for i in Out]
lid_locs:  list[str] = [h for h in h_locs if h != h21]

@dataclass(frozen=True)
class World:
    plates: dict[str, Plate]

    def __getattr__(self, loc: str) -> str:
        if loc in ('shape', 'dtype'):
            raise AttributeError
        for p in self.plates.values():
            if loc == p.loc:
                return p.id
            if loc == p.lid_loc:
                return f'lid({p.id})'
            if loc == p.target_loc:
                return f'target({p.id})'
        return 'free'

    # def __getitem__(self, loc: str) -> str:
    __getitem__ = __getattr__

    def update(self, p: Plate) -> World:
        return replace(self, plates={**self.plates, p.id: p})

    def success(self, p: Plate, cmds: list[run]=[]) -> Success:
        return Success(w=self.update(p), cmds=cmds)

@dataclass(frozen=True)
class run:
    device: str
    arg: Any | None = None
    id: JobId | None = None

@dataclass(frozen=True)
class Success:
    w: World
    cmds: list[run]

def world_locations(w: World) -> dict[str, str]:
    locs: list[str] = 'wash disp incu'.split()
    locs += incu_locs
    locs += h_locs
    locs += r_locs
    locs += out_locs
    return {loc: w[loc] for loc in locs}

@dataclass
class UniqueSupply:
    count: int = 0
    def __call__(self, prefix: str='') -> str:
        self.count += 1
        return f'{prefix}({self.count})'

    def reset(self) -> None:
        self.count = 0

unique = UniqueSupply()

from abc import ABC, abstractmethod

class ProtocolStep(ABC):
    @abstractmethod
    def step(self, p: Plate, w: World) -> Success | None:
        pass

@dataclass(frozen=True)
class incu_pop(ProtocolStep):
    target: str
    def step(self, p: Plate, w: World) -> Success | None:
        if p.loc in incu_locs and w[self.target] == 'free':
            id = JobId(unique('incu'))
            return w.success(
                replace(p, loc='incu', target_loc=self.target, waiting_for=id),
                [run('incu_get', p.loc, id=id)]
            )
        return None

@dataclass(frozen=True)
class incu_put(ProtocolStep):
    time: str
    def step(self, p: Plate, w: World) -> Success | None:
        if p.loc == h21 and p.lid_loc == 'self':
            for incu_loc in incu_locs:
                if w[incu_loc] == 'free':
                    id = JobId(unique('incu'))
                    return w.success(
                        replace(p, loc=incu_loc, waiting_for=UnresolvedTime(time=self.time, id=id)),
                        [
                            run('robot', 'generated/incu_put'),
                            run('incu_put', incu_loc, id=id),
                        ]
                    )
        return None

@dataclass(frozen=True)
class wash(ProtocolStep):
    arg1: str | None = None
    arg2: str | None = None
    def step(self, p: Plate, w: World) -> Success | None:
        if p.loc == h21 and p.lid_loc != 'self':
            id = JobId(unique('wash'))
            return w.success(
                replace(p, loc='wash', waiting_for=id),
                [
                    run('robot', 'generated/wash_put'),
                    run('wash', [self.arg1, self.arg2], id=id),
                ],
            )
        return None

@dataclass(frozen=True)
class disp(ProtocolStep):
    arg1: str | None = None
    arg2: str | None = None
    def step(self, p: Plate, w: World) -> Success | None:
        if p.loc == h21 and p.lid_loc != 'self':
            id = JobId(unique('disp'))
            return w.success(
                replace(p, loc='disp', waiting_for=id),
                [
                    run('robot', 'wash_get'),
                    run('disp', [self.arg1, self.arg2], id=id)
                ],
            )
        return None

@dataclass(frozen=True)
class RT_incu(ProtocolStep):
    time: str
    def step(self, p: Plate, w: World) -> Success | None:
        if p.loc == 'h21' and p.lid_loc == 'self':
            for r_loc in r_locs:
                if w[r_loc] == 'free':
                    return w.success(
                        replace(p, loc=r_loc, waiting_for=UnresolvedTime(self.time)),
                        [run('robot', f'generated/{r_loc}_put')]
                    )
        return None

@dataclass(frozen=True)
class to_output_hotel(ProtocolStep):
    def step(self, p: Plate, w: World) -> Success | None:
        if p.loc == 'h21' and p.lid_loc == 'self':
            for out_loc in out_locs:
                if w[out_loc] == 'free':
                    return w.success(
                        replace(p, loc=out_loc),
                        [run('robot', f'generated/{out_loc}_put')]
                    )
        return None

def moves(p: Plate, w: World) -> Iterator[Success]:
    if p.waiting_for is not None:
        return

    # disp to h21
    if p.loc == 'disp' and w.h21 == 'free':
        assert p.waiting_for is None
        yield w.success(
            replace(p, loc=h21),
            [run('robot', 'generated/disp_get')]
        )

    # wash to h21
    if p.loc == 'wash' and w.h21 == 'free':
        assert p.waiting_for is None
        yield w.success(
            replace(p, loc=h21),
            [run('robot', 'generated/wash_get')]
        )

    # incu to h21
    if p.loc == 'incu' and w.h21 == 'free':
        assert p.waiting_for is None
        yield w.success(
            replace(p, loc=h21),
            [run('robot', 'generated/incu_get')]
        )

    # RT to h21
    if p.loc in r_locs and w.h21 == 'free':
        assert p.waiting_for is None
        yield w.success(
            replace(p, loc=h21),
            [run('robot', f'generated/{p.loc}_get')]
        )

    if 1:
        # h## to h21
        if p.loc in h_locs and w.h21 == 'free':
            yield w.success(
                replace(p, loc=h21),
                [run('robot', f'generated/{p.loc}_get')]
            )

        # h21 to h##
        if p.loc == h21:
            for h_loc in h_locs:
                if w[h_loc] == 'free':
                    yield w.success(
                        replace(p, loc=h_loc),
                        [run('robot', f'generated/{h_loc}_put')]
                    )
                    break

    # lid: move lid on h## to self
    if p.loc == h21 and p.lid_loc in lid_locs:
        yield w.success(
            replace(p, lid_loc='self'),
            [run('robot', f'generated/lid_{p.lid_loc}_get')],
        )

    # delid: move lid on self to h##
    if p.loc == h21 and p.lid_loc == 'self':
        for lid_loc in lid_locs:
            if w[lid_loc] == 'free':
                yield w.success(
                    replace(p, lid_loc=lid_loc),
                    [run('robot', f'generated/lid_{lid_loc}_put')],
                )
                break

# Cell Painting Workflow
protocol: list[ProtocolStep] = [
    # 2 Compound treatment: Remove (80%) media of all wells
    incu_pop(target='wash'),
    wash(),

    # 3 Mitotracker staining
    disp('peripump 1', 'mitotracker solution'),
    incu_put('30 min'),
    incu_pop(target='wash'),
    wash('pump D', 'PBS'),

    # 4 Fixation
    disp('Syringe A', '4% PFA'),
    RT_incu('20 min'),
    wash('pump D', 'PBS'),

    # 5 Permeabilization
    disp('Syringe B', '0.1% Triton X-100 in PBS'),
    RT_incu('20 min'),
    wash('pump D', 'PBS'),

    # 6 Post-fixation staining
    disp('peripump 2', 'staining mixture in PBS'),
    RT_incu('20 min'),
    wash('pump D', 'PBS'),

    # 7 Imaging
    to_output_hotel(),
]

from collections import deque

def bfs(w0: World, moves, max_fuel = 10_000) -> Tuple[World, list[run]] | None:
    q: deque[Tuple[World, list[run]]] = deque([(w0, [])])
    visited = set()
    fuel = max_fuel
    while q and fuel > 0:
        fuel -= 1
        w, cmds = q.popleft()
        rw = repr(w)
        if rw in visited:
            continue
        visited.add(rw)
        # pp(w.plates, world_locations(w))
        for p in w.plates.values():
            if p.waiting_for is not None:
                continue
            if not p.queue:
                continue
            if res := p.top().step(p.pop(), w):
                # pp(p, p.top())
                pp(max_fuel - fuel)
                return (res.w, cmds + res.cmds)
            for res in moves(p, w):
                if res:
                    q.append((res.w, cmds + res.cmds))
    return None

p0: list[Plate] = [
    Plate('Ada', incu_locs[0], queue=protocol),
    Plate('Bob', incu_locs[1], queue=protocol),
    Plate('Cal', incu_locs[2], queue=protocol),
    Plate('Deb', incu_locs[3], queue=protocol),
    Plate('Eve', incu_locs[4], queue=protocol),
    Plate('AII', incu_locs[5], queue=protocol),
    Plate('BII', incu_locs[6], queue=protocol),
    Plate('CII', incu_locs[7], queue=protocol),
    Plate('DII', incu_locs[8], queue=protocol),
    Plate('EII', incu_locs[9], queue=protocol),
    Plate('Ad2', incu_locs[10], queue=protocol),
    Plate('Bo2', incu_locs[11], queue=protocol),
    Plate('Ca2', incu_locs[12], queue=protocol),
    Plate('De2', incu_locs[13], queue=protocol),
    Plate('Ev2', incu_locs[14], queue=protocol),
    Plate('AI2', incu_locs[15], queue=protocol),
    Plate('BI2', incu_locs[16], queue=protocol),
    Plate('CI2', incu_locs[17], queue=protocol),
    Plate('DI2', incu_locs[18], queue=protocol),
    Plate('EI2', incu_locs[19], queue=protocol),
]

w0 = World(dict({p.id: p for p in p0}))

w = w0

all_cmds = []

while 1:
    # pp('running bfs...')
    # for p in w.plates.values():
    #     pp(p, len(p.queue), p.queue[:1])
    res = bfs(w, moves)
    if not res:
        break
    w, cmds = res
    all_cmds += cmds
    # pp('res:', w.plates, cmds)

    for p in w.plates.values():
        if p.target_loc == p.loc:
            w = w.update(replace(p, target_loc=None))

    for p in w.plates.values():
        if p.waiting_for:
            w = w.update(replace(p, waiting_for=None))

print('done?')
pp(all_cmds)
pp({
    p.id: (*astuple(p)[:4], len(p.queue))
    for p in w.plates.values()
})
pp(w.plates)





