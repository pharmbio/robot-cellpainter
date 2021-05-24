# robot remote control

dev dependencies: flask, pandas, scipy

optional dev dependency: pyright

rewrite in progress

| | |
| --- | --- |
|                     | _a command line interface_
| cli.py              | make the robots in the lab do things!
|                     | _notes_
| notes.md            | things I have learned working on this
|                     | _nice robotarm move representations_
| moves.py            | robotarm positions in mm XYZ and degrees RPY
| robotarm.py         | send moves to the robotarm and its gripper
|                     | _the other lab robots_
| robots.py           | uniform control over the washer, dispenser, incubator and the robotarm
| protocol.py         | cell painting protocol
| protocol_vis.py     | visualize timings of the cell painting protocol
| analyze_log.py      | timings statistics for a cell painting log
|                     | _communication with the robotlab network_
| sync.sh             | rsync local copy with the robotlab NUC
| secrets-template.sh | fill this in with the missing pieces and then source its env vars
|                     | _working with programs made as urscripts on the teach pendant_
| scriptparser.py     | parses the scripts and resolves locations in UR scripts
| scriptgenerator.py  | converts resolved UR scripts to the nice representations
| copyscripts.sh      | copy the scripts made on the teach pendant to `scripts/`
|                     | _utils_
| utils.py            | pretty printing and other small utils
| color.py            | print in color
| viable.py           | a viable alternative to front-end programming
|                     |
