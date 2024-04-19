#! /usr/bin/env python3
import os, time
from pathListForTest import caseNameList, intfDirList, rawDir, \
    SLCDir, workAbsoluteDir, pythonCommandListPath

for caseName in caseNameList:
    startTime = time.time()
    os.chdir(workAbsoluteDir+caseName)
    os.system('pwd')
    os.system('cleanup all')
    os.system('cp -r '+pythonCommandListPath+'README_'+caseName+'.txt .')
    os.system('./README_'+caseName+'.txt > log.txt')
    elapsedTime = time.time()-startTime
    with open('timeSpentLog.txt', 'a') as f:
        f.write(caseName+' used '+str(elapsedTime)+' s \n')

os.chdir(workAbsoluteDir)
os.system('python checkTest.py')
