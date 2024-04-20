#! /usr/bin/env python3

workAbsoluteDir = '/scratch/gmtsar.py.dev/py.test/'
pythonCommandListPath = workAbsoluteDir+'pythonREADME/'

rawDir = 'raw'
SLCDir = 'SLC'

intfDirList = {
                'S1_Ridgecrest_EQ': ['F1/intf/2019184_2019196', 'F2/intf/2019184_2019196', 
                                    'F3/intf/2019184_2019196', 'merge', 'H_res'],
                'TSX_SLC_Hawaii' : ['intf/2012166_2012342'],
                'ALOS_Baja_EQ' : ['intf/2009351_2010124'],
                'ALOS_ERSDAC_L1.0' : ['intf/2010141_2010187'],
                'S1A_SLC_TOPS_LA' : ['F1/intf/2015145_2015157', 'F2/intf/2015145_2015157', 
                                      'F3/intf/2015145_2015157', 'merge'],
                'S1A_SLC_TOPS_Greece' : ['F1/intf/2015308_2015320', 'F2/intf/2015308_2015320',
                                        'F3/intf/2015308_2015320','merge'],
                'ALOS_SLC_L1.1' : ['intf/2010095_2010141'], 
                'ERS_Hector_EQ' : ['intf/1999258_1999293'], 
                'RS2_SLC_Hawaii' : ['intf/2011134_2011230'],
                'ENVI_Baja_EQ' : ['intf/2010087_2010122'],
                'ENVI_Baja_EQ_SLC' : ['intf/2010087_2010122'],
                'CSK_RAW_Hawaii' : ['intf/2014004_2014020'],
                'CSK_SLC_Italy' : ['intf/2009101_2009133']
               }

caseNameList = [
        'S1_Ridgecrest_EQ',
        'TSX_SLC_Hawaii',
        'ALOS_Baja_EQ',
        'ALOS_ERSDAC_L1.0', 
        'S1A_SLC_TOPS_LA', 'S1A_SLC_TOPS_Greece', 'ALOS_SLC_L1.1', 'ERS_Hector_EQ', 'RS2_SLC_Hawaii',
                'ENVI_Baja_EQ', 'ENVI_Baja_EQ_SLC','CSK_RAW_Hawaii',
                'CSK_SLC_Italy'
                ]



