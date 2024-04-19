#! /usr/bin/env python3
"""
# gmtsar_lib.py is part of pyGMTSAR. 
# It hosts commonly used functions similar to CSH.
# Dunyu Liu, 20230202.

# check_file_report
# grep_value
# replace_strings
# file_shuttle
"""

########################################
    ## The following block loads configuration files from config.ini
    ## Currently keep it but may phase out in the future.
    ########################################
    
    # print('P2P 0: load config.ini ... ...')
    # config   = configparser.ConfigParser()
    # config.read('config.ini')
    
    # # stage, which stage to process, int.
    # stage    = int(config['params']['proc_stage'])
    # s_stage  = config['params']['skip_stage']
    # #s_stage= config
    # print(" ")
    # print('P2P 0: proc_stage = ', stage)
    # print('P2P 0: skip_stage = ', s_stage)

    # skip_1   = 0
    # skip_2   = 0
    # skip_3   = 0
    # skip_4   = 0
    # skip_5   = 0
    # skip_6   = 0
    
    # if s_stage != '':
        # print(" ")
        # print("P2P 0: skipping stages are ", s_stage, ' ... ...')
    
    # tmp = config['params']['skip_master'] # tmp is a string. Needs to convert it to numbers for manipulation later.
    # if tmp == '':
        # skip_master = 0
    # else:
        # skip_master = int(tmp)

    # if skip_master == 2:
        # skip_4 = 1
        # skip_5 = 1
        # skip_6 = 1
        # print("P2P 0: skipping stages 4,5, and 6 as skip_master is set to 2 ...")
    
    # print("P2P 0: skip_master = ", skip_master)
    
    # print('P2P 0: loading num_patches, near_range, earth_radius, fd (floats)')
    # num_patches   = config['params']['num_patches']
    # near_range    = config['params']['near_range']
    # earth_radius  = config['params']['earth_radius']
    # fd            = config['params']['fd1']
    
    # print('P2P 0: loading topo_phase, topo_interp_mode (ints)')
    # topo_phase    = int(config['params']['topo_phase'])
    # topo_interp_mode = int(config['params']['topo_interp_mode'])

    # if topo_interp_mode == '':
        # topo_interp_mode = 0

    # shift_topo    = int(config['params']['shift_topo'])
    # switch_master = int(config['params']['switch_master'])
    # filter        = config['params']['filter_wavelength']
    # compute_phase_gradient = config['params']['compute_phase_gradient']
    # iono          = config['params']['correct_iono']
    # if iono == '':
        # iono = 0
    
    # iono_filt_rng = config['params']['iono_filt_rng']
    # iono_filt_azi = config['params']['iono_filt_azi']
    # iono_dsamp    = config['params']['iono_dsamp']
    # iono_skip_est = config['params']['iono_skip_est']
    
    # # spec_div could be missing.
    # if config.has_option('params','spec_div') == True:
        # spec_div      = config['params']['spec_div']
    # else:
        # spec_div      = 0
    
    # # spec_mode could be missing.
    # if config.has_option('params','spec_mode') == True:
        # spec_mode     = config['params']['spec_mode']
    # else:
        # spec_mode     = ''
        
    # dec           = config['params']['dec_factor']
    # threshold_snaphu  = float(config['params']['threshold_snaphu'])
    # threshold_geocode = float(config['params']['threshold_geocode'])
    # #if config.has_option('params','region_cut') == True:
    # region_cut    = config['params']['region_cut']
    # #else:
    # print('P2P 0: region_cut =', region_cut)
    # print((region_cut==''))
    # print((region_cut==None))
    
    # mask_water    = config['params']['mask_water']
    # print('P2P 0: mask_water =', mask_water)
    
    # # switch_land could be missing 
    # if config.has_option('params','switch_land')  == True:
        # switch_land   = config['params']['switch_land']
    # else: 
        # switch_land   = ''
    # print('P2P 0: switch_land =', switch_land)    
    # defomax       = config['params']['defomax']
    
    # # range_dec could be missing
    # if config.has_option('params','range_dec')    == True:
        # range_dec     = config['params']['range_dec']
    # else:
        # range_dec     = ''
        
    # if config.has_option('params','range_dec')    == True:
        # azimuth_dec   = config['params']['azimuth_dec']
    # else:
        # azimuth_dec   = ''
    # if config.has_option('params', 'SLC_factor')  == True:
        # SLC_factor    = config['params']['SLC_factor']
    # else: 
        # SLC_factor    = ''
        
    # near_interp   = config['params']['near_interp']
    # master        = sys.argv[2]
    # aligned       = sys.argv[3]

    # print(config.items('params'))
    # print(' ')