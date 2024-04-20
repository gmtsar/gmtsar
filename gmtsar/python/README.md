# GMTSAR Python framework

## Installation
Assuming $GMTSAR is where GMTSAR is installed. To get Python framework in work, simply <br/>
```
chmod -R 755 $GMTSAR/gmtsar/python/utils
cp $GMTSAR/gmtsar/python/utils/* $GMTSAR/bin
```
Then, you can type in your terminal 
```
p2p_processing 
```
to see if help information is shown.

# Testing for developers
Assuming $SCRATCH is where you want to carry out the testing of GMTSAR Python framework for all supported SATs, <br/>
please put all testing datasets under $SCRATCH/py.test/ <br/>
and copy files and folders from $GMTSAR/python/testingSystem/* to $SCRATCH </br>

Then, type in your terminal 
```
python3 runAllTest.py
```
News compared to csh framework:
1. Computing time will be collected in timeSpentLog.txt, and output from computation is piped to log.txt under each case folder. <br/>
2. checkTest.py is developed to compared results to exisiting results from reference csh frameowrk runs. To install necessary Python packages, please see $GMTSAR/gmtsar/python/install.packages.for.python.testing.sh. .png and .grd files will be compared.
3. SAT datasets in caseNameList in pathListForTest.py are now testesd against results run by csh framework.

Currently, it takes less than a day to get all supported SATs tested.
