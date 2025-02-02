import meds
import psfex
import bfd
from bfd import momentcalc as mc
from bfd.momenttable import TemplateTable, TargetTable
from .read_meds_utils import Image, MOF_table, DetectionsTable,save_targets
from .utilities import update_progress, save_obj, load_obj
import glob
import numpy as np
import pandas as pd
import pyfits as pf
from matplotlib import pyplot as plt
import ngmix.gmix as gmix
import ngmix           
import timeit
import pickle
import os
import argparse
import gc
import math
import time, sys
import multiprocessing
from functools import partial
import sys      
import copy
from astropy import version 
import astropy.io.fits as fits
import frogress
from bfd.keywords import *



'''
make a code that assembles everything, then it must call the create_tiers from Gary.


python createTiers.py X.fits --snMin --snMax  --fluxMin --fluxMax

'''

def produce_sn(t):
    return t[1].data['moments'][:,0]/np.sqrt(t[1].data['covariance'][:,0])

def produce_cov(t):
    return (t[1].data['covariance'][:,0])

def produce_mf(t):
    return t[1].data['moments'][:,0]

def make_targets(output_folder,**config):
    if config['MPI']:
        from mpi4py import MPI 
    comm = MPI.COMM_WORLD
    if comm.rank==0:
        
        # the code needs to read in all the fits files, assign noisetiers, and save the final target file.
        # It distinguishes between image sims files and normal files.
        params_template = {}
        params_template['n'] = config['n'] 
        params_template['sigma'] =  config['sigma']     
        add_labels = ['','ISp_','ISm_']
        
        # make the list for simulted tiles, they need to be loaded in the same order for noise cancelling.
        files_simulated_p = glob.glob(output_folder+'/targets/{1}{0}*.fits'.format('targets','ISp_'))
        files_simulated_m = [f.replace('ISp_','ISm_') for f in files_simulated_p]      
        
        #print (add_labels)
        for add in add_labels:
            nlost = 0
            
            for xx,tt in enumerate(['targets']):
                #'''
                
                
                if not os.path.exists(output_folder+'/{1}{0}_sample_g.fits'.format(tt,add)):
                    # read all the target files 
                    files = glob.glob(output_folder+'/targets/{1}{0}*.fits'.format(tt,add))
                
                    if add =='ISp_':
                        files = files_simulated_p
                    if add =='ISm_':
                        files = files_simulated_m
                    list_target = []



                    if len(files)>0:
                        run_count = 0



                        hdulist = pf.HDUList([pf.PrimaryHDU()])
                        # assign noisetiers **********************************************************************
                        file_removed = False

                        for ii in frogress.bar(range(len(files))):
                            file = files[ii]
                            try:
                                mute = pf.open(file)
                            except:
                                os.remove(file)
                                file_removed = True
                            if ii ==0:
                                occ  = mute[1].data['covariance'][:,0]
                                mf  = mute[1].data['moments'][:,0]
                            else:
                                occ = np.hstack([occ,mute[1].data['covariance'][:,0]])
                                mf = np.hstack([mf,mute[1].data['moments'][:,0]])
                        if file_removed:
                            print ('Need to re-run measure targets.')
                            sys.exit()

                        # check if there're NaN (it can happen when simulatin images)
                        mask= (~np.isnan(occ)) & (occ>0.) & (~np.isnan(mf)) #& (noisetier == NOISE_TIER_MASK)

                        print (len(mask[mask]),len(mask))
                        # First we're going to create a table the concatenates all the current tables
                        cols = [] 

                        names = [mute[1].columns[i].name for i in range(len(mute[1].columns))]
                        if not ('AREA' in names):
                            cols.append(pf.Column(name="AREA",format="K",array=0*np.ones_like(mask)))#noisetier[mask]*np.ones_like(noisetier[mask])))


                        cols.append(pf.Column(name="NOISETIER",format="K",array=0*np.ones_like(mask)))#noisetier[mask]*np.ones_like(noisetier[mask])))
                        new_cols = pf.ColDefs(cols)
                        hdu = pf.BinTableHDU.from_columns(mute[1].columns + new_cols)
                        hdu.data['NOISETIER'][~mask] = -1

                        #except:
                        #    pass
                        for key in (hdrkeys['weightN'],hdrkeys['weightSigma']):
                            hdu.header[key] = mute[0].header[key]
                        for cname in mute[1].columns.names:
                            sofar = 0
                            for ii, file in enumerate(files):
                                mute = pf.open(file)
                                mask =( ~np.isnan(mute[1].data['covariance'][:,0]))& (mute[1].data['covariance'][:,0]>0.) & ( ~np.isnan(mute[1].data['moments'][:,0]))

                                nlost+=len(mask[~mask])
                                nn = len(mask)
                                hdu.data[cname][sofar:sofar+nn] = mute[1].data[cname]
                                sofar += nn  

                                
                        mask= (~np.isnan(occ)) & (occ>0.) & (~np.isnan(mf)) #& (noisetier == NOISE_TIER_MASK)
                        
                        #I think we can assign random values that are different from nan here ****
                        indx_ = np.arange(hdu.data['covariance'].shape[0])[mask]
                        indx = indx_[np.random.randint(0,len(indx_),len(mask[~mask]))]
                        hdu.data['covariance'][~mask,:] = hdu.data['covariance'][indx,:]

                        if 1 ==1:
                            mask__ = (~mask) 
                            hdu.data['moments'][mask__,:] = 0.
                            #hdu.data['covariance'][mask__,:] = 1. # I think we can assign random values that are different from nan here ****
                            hdu.data['AREA'][mask__] = -1.
    
                        for key in (hdrkeys['weightN'],hdrkeys['weightSigma']):
                            hdulist[0].header[key] = mute[0].header[key]
                        hdulist[0].header['STAMPS'] = mute[0].header['STAMPS']
                        #hdulist[0].header['NLOST'] = nlost
                 
                        hdulist.append(hdu)
                        del hdu

                        try:
                            hdulist.writeto(output_folder+'/{1}{0}_sample_g.fits'.format(tt,add))
                        except:
                            try:
                                hdulist.writeto(output_folder+'/{1}{0}_sample_g.fits'.format(tt,add),clobber = True)# 
                            except:
                                pass


        # MAKE NOISE TIERS *******************************************************************************
        

                    
        
        filex = (output_folder+'/{1}{0}_sample_g.fits'.format(tt,'ISp_'))
        if os.path.exists(filex):
            pass
        else:
            filex = (output_folder+'/{1}{0}_sample_g.fits'.format(tt,''))
            
            
        
        
        print ('')
        print (filex)
        print ('')
        
        
        if os.path.exists(output_folder+'/noisetiers.fits'):
            os.remove(output_folder+'/noisetiers.fits')
        os.system('python createTiers.py {0} --snMin {1} --snMax  {2} --fluxMin {3} --fluxMax {4} --output {5}'.format(filex,config['sn_min'],config['sn_max'],config['Mf_min'],config['Mf_max'],output_folder+'/noisetiers.fits'))
        
        # ASSIGN NOISE TIERS ********************
        from bfd import TierCollection

        tc = TierCollection.load(output_folder+'/noisetiers.fits')
        
        # here need to load it and assign noise tiers to the fits file again ---
        for add in add_labels:
            nlost = 0
            hdulist = pf.HDUList([pf.PrimaryHDU()])
                    
            if os.path.exists(output_folder+'/{1}{0}_sample_g.fits'.format(tt,add)):
                print ('saving')
                for xx,tt in enumerate(['targets']):
                    print (output_folder+'/{1}{0}_sample_g.fits'.format(tt,add))
                    m_ = pf.open(output_folder+'/{1}{0}_sample_g.fits'.format(tt,add))
                    for key in (hdrkeys['weightN'],hdrkeys['weightSigma']):
                        hdulist[0].header[key] = m_[0].header[key]
                    hdulist[0].header['STAMPS'] = m_[0].header['STAMPS']
            
            
                    n_ = tc.assign(m_[1].data['covariance'])
                    noise_tiers = np.zeros(m_[1].data['covariance'].shape[0]).astype(np.int)
                    for key in n_.keys():
                        noise_tiers[n_[key]]=key

                    # dismis stuff that doesn't pass the cuts ***********
                    
                    mask = (produce_sn(m_)>config['sn_min']) & (produce_sn(m_)< config['sn_max']) & (produce_mf(m_)>config['Mf_min']) & (produce_mf(m_)< config['Mf_max']) 

                    hdu = pf.BinTableHDU.from_columns(m_[1].columns)
                    hdu.data['NOISETIER'] = noise_tiers
                    
                    


                    print (len(mask[mask]),len(mask))
                    m__ = (~mask) & (hdu.data['AREA']==0)
                    hdu.data['AREA'][m__] = 1

                    for key in (hdrkeys['weightN'],hdrkeys['weightSigma']):
                        hdu.header[key] = m_[0].header[key]
                        
                    hdulist.append(hdu)

                        
                        
                        
                        

                    # Next create an image of mean covariance matrix for each tier
                    hdr = hdulist[0].header
                    unique_tiers = np.unique(noise_tiers)
                    unique_tiers = unique_tiers[unique_tiers != -1]
                    
                    for tier in unique_tiers:

                        # Build covariance matrix for even parity
                        mask = noise_tiers == tier
                        nn = 5
                        data = np.zeros((nn,nn))
                        index = 0
                        
                        for i in range(nn):
                            for j in range(i,nn):
                                data[i,j] = np.mean(m_[1].data['covariance'][mask,index])
                                data[j,i] = np.mean(m_[1].data['covariance'][mask,index])
                                index += 1
                        hdu = pf.ImageHDU(data)
                        hdu.header[hdrkeys['weightN']] =  m_[1].header[hdrkeys['weightN']]
                        hdu.header[hdrkeys['weightSigma']] =m_[1].header[hdrkeys['weightSigma']]
                        hdu.header['TIERNAME'] = tier
                        hdu.header['TIERLOST'] = 0
                        # Record mean covariance of odd moments in header

                        
                        '''
                        # saved in order M0xM0, M0xMR, M0xM1, M0xM2, M0xMC,
                        # MRxMR, MRxM1, MRxM2, MRxMC, M1xM1, M1xM2, M1xMC,
                        # M2xM2, M2xMC, MCxMC (total of 15)
                        
                        '''
                        xx =0.5*np.mean(m_[1].data['covariance'][:,1]+m_[1].data['covariance'][:,2])
                        #0.5*(m_[1].data['covariance'][:,3])
                        yy = 0.5*np.mean(m_[1].data['covariance'][:,1]-m_[1].data['covariance'][:,2])
                        
                        #xyCov = 0.5 * np.array( [[ cov[m.M0,m.MR]+cov[m.M0,m.M1], cov[m.M0,m.M2] ],
                        #     [ cov[m.M0, m.M2], cov[m.M0,m.MR]-cov[m.M0,m.M1]]] )
                            
                            
                        
                        mean_c = 0.5*(yy+xx)
                        hdu.header['COVMXMX'] = mean_c
                        hdu.header['COVMXMY'] = 0.5*np.mean(m_[1].data['covariance'][:,3])
                        hdu.header['COVMYMY'] = mean_c
                        hdulist.append(hdu)
                        

                        del hdu
                    # assign noisetiers -1
                    print (np.unique(hdulist[1].data['NOISETIER']))
                    mask = noise_tiers ==-1
                    if len(mask[mask])>0:
                        cvm = [hdulist[ii+2].data[0,0] for ii in range(len(hdulist)-2)]
                        ttu = np.array([hdulist[ii+2].header['TIERNAME'] for ii in range(len(hdulist)-2)])
                        hdulist[1].data['NOISETIER'][mask] =  ttu[np.array([np.argmin((u-cvm)**2) for u in produce_cov(hdulist)[mask]])]
                    print (np.unique(hdulist[1].data['NOISETIER']))

                        
                    try:
                        hdulist.writeto(output_folder+'/{1}{0}_sample_g.fits'.format(tt,add))
                    except:
                        try:
                            hdulist.writeto(output_folder+'/{1}{0}_sample_g.fits'.format(tt,add),clobber = True)# 
                        except:
                            pass
          
