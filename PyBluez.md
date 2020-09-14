# How to install PyBluez for Inkscape silhouette plugin

## On OSX:

#### Python 2.7 (MacPorts version)
-  dowload [lightblue](https://github.com/0-1-0/lightblue-0.4)
-  go to downloaded (and extracted) folder
-  (Not entirely sure but maybe I already head PyObjC  installed via pip2.7 at that moment, so you might need that too if the next step fails)
-  run `sudo python2.7 setup.py install` (make sure `which python2.7` indeed points to your MacPorts Python version) to install `LightAquaBlue.framework` into  `/Library/Frameworks`
-  Copy the created framework from `/Library/Frameworks/LightAquaBlue.framework` to `/opt/local/Library/Frameworks/Python.framework/Versions/2.7/lib/python2.7/site-packages/lightblue`  
   *Note:* I guess this is only necessary when using the MacPorts Python version (/opt/local is my MacPorts prefix, yours might differ)
-  Install pybluez via
   ```
   sudo pip-2.7 install git+https://github.com/pybluez/pybluez.git@57df0b1a332ccffe77e850e5e7c10fd856bb640f
   ```
   this will install pybluez version 0.22 (last compatible with Python 2), but other than the version tagged 0.22 in the repo this one compiles just fine (will have a look whether there is a later commit that also works)
-  Check that everything works: open python interpreter `python2.7` and enter (while your silhouette device switched on and connected via bluetooth)
   - `import bluetooth`
   - `nearby_devices = bluetooth.discover_devices(lookup_names=True)`
   - `len(nearby_devices)`  (should return number > 0)
   - `nearby_devices` (should display a list of devices including your device)

#### Python 2.7 (Shipped with OSX)
- Same as above but copy the framework to (and using the shipped python executable off course)
  ```
  /Library/Python/2.7/site-packages/lightblue/
  ```

#### Python 3.8 (MacPorts version)
- Same as above but copy the framework to (and using the shipped python executable off course)
  ```
  /opt/local/Library/Frameworks/Python.framework/Versions/3.8/lib/python3.8/site-packages/lightblue
  ```
- and install pybluez via
   ```
   sudo pip-3.8 install git+https://github.com/pybluez/pybluez.git@0.23
   ```

## On Ubuntu (tested on Ubuntu 16.04)
#### Python2
- Make sure to install dependencies of PyBluez:
  ```
  sudo apt install python2.7-dev libbluetooth-dev
  ```
- Then just install PyBluez version 0.22 via pip2:
  ```
  sudo pip2 install git+https://github.com/pybluez/pybluez.git@0.22
  ```
-  Check that everything works: open python interpreter `python2` and enter (while your silhouette device switched on and connected via bluetooth)
   - `import bluetooth`
   - `nearby_devices = bluetooth.discover_devices(lookup_names=True)`
   - `len(nearby_devices)`  (should return number > 0)
   - `nearby_devices` (should display a list of devices including your device)

#### Python3
- Analogous to Python2:
- Make sure to install dependencies of PyBluez:
  ```
  sudo apt install python3-dev libbluetooth-dev
  ```
- Then just install PyBluez via pip3:
  ```
  sudo pip3 install pybluez
  ```
-  Check that everything works: open python interpreter `python3` and enter (while your silhouette device switched on and connected via bluetooth)
   - `import bluetooth`
   - `nearby_devices = bluetooth.discover_devices(lookup_names=True)`
   - `len(nearby_devices)`  (should return number > 0)
   - `nearby_devices` (should display a list of devices including your device)
