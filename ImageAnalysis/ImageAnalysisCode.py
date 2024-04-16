# -*- coding: utf-8 -*-
"""
Created on Mon Sep  5 17:40:14 2022

@author: Sommer Lab
"""
import matplotlib.pyplot as plt
import numpy as np 
#import matplotlib.patches as patches
#import lmfit
#from lmfit import Parameters
import configparser 
#import rawpy
#import imageio 
import glob
from scipy.optimize import curve_fit
from scipy.ndimage import rotate
from scipy.ndimage import gaussian_filter1d
from scipy import signal
from skimage.filters import threshold_otsu
from scipy.ndimage import rotate

import os
import PIL
import datetime
import pandas as pd
from mpl_toolkits.axes_grid1 import make_axes_locatable

from ImageAnalysis.ExperimentParameters import ExperimentParams


def GetDataLocation(date, DataPath='D:\Dropbox (Lehigh University)\Sommer Lab Shared\Data'):
    return os.path.join(DataPath, datetime.datetime.strptime(date, '%m/%d/%Y').strftime('%Y/%m-%Y/%d %b %Y'))

def GetExamRange(examNum, examFrom=None, repetition=1):
    if examNum is None or examNum == 'all':
        return None, None
    
    examNum = examNum * repetition

    if examFrom is None:
        examFrom = -examNum
    else:
        examFrom = examFrom * repetition
        
    examUntil = examFrom + examNum
    if examUntil == 0:
        examUntil = None
    return examFrom, examUntil
    

def LoadConfigFile(dataFolder=".", configFileName='config.cfg',encoding="utf-8"): 
    config_file = dataFolder + "//" + configFileName
    config = configparser.ConfigParser()
    config.read(config_file,encoding=encoding)
    return config
    
def LoadTOF(dataFolder='.', TOF_filename='TOF_list.txt', units_of_tof='ms'):    
    tof_list = np.loadtxt(dataFolder + "//" + TOF_filename)
    return tof_list, units_of_tof 
    

# def loadRAW(filename):
#     with rawpy.imread(filename) as raw:
#         bayer = raw.raw_image
#         print(type(bayer))    
#     return bayer

def loadRAW(params, filename):
    file = open(filename,"rb")
    content = file.read()
    data_array = np.frombuffer(content, dtype = params.data_type)
    rows = 964
    cols = 1288
    print("max value: {}".format(np.max(data_array)))
    data_array = np.reshape(data_array, (rows, cols))
    return data_array


def loadSeriesRAW(params, picturesPerIteration=1 ,  data_folder= "."):
    file_names = glob.glob(os.path.join(data_folder,'*.raw'))
    number_of_pics = len(file_names)
    number_of_iterations = int(number_of_pics/picturesPerIteration)
    rows = 964
    cols = 1288
    image_array = np.zeros((number_of_iterations, picturesPerIteration, rows, cols))
    for iteration in range(number_of_iterations):
        for picture in range(picturesPerIteration):
            x = iteration*picturesPerIteration + picture
            filename = file_names[x]  
            image_array[iteration, picture,:,:] = loadRAW(params, filename)           
    return image_array


#filename must include full path and extension
def loadPGM(filename, file_encoding = 'binary'):
    if file_encoding == 'text':
        with open(filename, 'r') as f:
            filetype = f.readline()
            if filetype.strip() != "P2":
                raise Exception("wrong format, should be P2")
                             
            res = f.readline().split()
            cols = int(res[0])
            rows = int(res[1])
            
            # pixel_number = rows*cols            
            # maxval = f.readline()
            
            datastrings = f.read().split()
            data =list( map(int, datastrings))
            rows2discard = 2
            data = data[(cols*rows2discard):] # discard the first two rows
            rows = rows-rows2discard
            data_array = np.array(data)
            data_array = np.reshape(data_array, (rows,cols))
            #print("max value in image array = {}".format(np.max(data_array)))
    if file_encoding == 'binary':
        image = PIL.Image.open(filename)#, formats=["PGM"]))
        data_array = np.asarray(image, dtype=np.uint16)
        rows, cols = np.shape(data_array)
        rows2discard = 2
        data_array = data_array[rows2discard: , :]
    return data_array 
    
def rebin(arr, new_shape):
    shape = (new_shape[0], arr.shape[0] // new_shape[0],
             new_shape[1], arr.shape[1] // new_shape[1])
    return arr.reshape(shape).mean(-1).mean(1)

def rebin2(arr, bins):
    #Bins = (binx, biny)
    #this function throws away excess matrix elements
    new_shape = (arr.shape[0]//bins[0], arr.shape[1]//bins[1])
    return rebin(arr[:bins[0]*new_shape[0], :bins[1]*new_shape[1]], new_shape)


# to load a numbered series of FLIR .pgm images into a 4D numpy array
# filenames must be in this format: root+number.pgm. Number must start from 1 
# n_params is the number of embedded image information fields which are checked, values between 0 to 10, default 0 
# zero is black, maxval is white

def loadSeriesPGM(picturesPerIteration=1 ,  data_folder= "." , background_file_name="", binsize=1, 
                  file_encoding = 'binary', examFrom=0, examUntil=None, return_fileTime=0):
    if examFrom:
        examFrom *= picturesPerIteration
    if examUntil:
        examUntil *= picturesPerIteration
        
    file_names = sorted(glob.glob(os.path.join(data_folder,'*.pgm')))[examFrom: examUntil]
    
    return loadFilesPGM(file_names, picturesPerIteration, background_file_name, 
                        binsize, file_encoding = file_encoding, 
                        return_fileTime = return_fileTime)


def loadFilesPGM(file_names, picturesPerIteration=1, background_file="", binsize=1, 
                 file_encoding = 'binary', return_fileTime=0):
    number_of_pics = len(file_names)
    number_of_iterations = int(number_of_pics/picturesPerIteration)

# read the background image into a 1d numpy array whose size is pixel_nimber
# width and height of the background images should be the same as the series of images 

    first_image = loadPGM(file_names[0], file_encoding = file_encoding)  
    rows, cols = np.shape(first_image)
    if background_file:
        #bg_filename = data_folder + "\\" + background_file_name   
        bg_data_array = loadPGM(background_file, file_encoding = file_encoding)
        
# this part read the series of images, background corrects them, loads them into a 4D numpy array  
# outermost dimension's size is equal to the number of iterations, 
# 2nd outer dimensions size is number of pictures per iteration
# 3rd dimensions size is equal to the height of the images  
    image_array = np.zeros((number_of_iterations, picturesPerIteration, rows//binsize, cols//binsize))
    fileTime = []
    for iteration in range(number_of_iterations):
        for picture in range(picturesPerIteration):              
            x = iteration*picturesPerIteration + picture
            
            if picture == 0 and return_fileTime:
                fileTime.append( datetime.datetime.fromtimestamp( os.path.getctime(file_names[x]) ) )
                
            if x > 0:
                data_array_corrected = loadPGM(file_names[x], file_encoding = file_encoding)
            else:
                data_array_corrected = first_image
                
            if background_file:
                data_array_corrected -= bg_data_array
            
            if binsize > 1:
                data_array_corrected = rebin2(data_array_corrected, (binsize, binsize))
            
            image_array[iteration, picture,:,:] = data_array_corrected
    
    if return_fileTime:
        return image_array, fileTime
    else:
        return image_array


# to load a series of non-spooled Andor .dat images into a 4D numpy array
def LoadAndorSeries(params, root_filename, data_folder= "." , background_file_name= "background.dat"):
        """
        Parameters
        ----------
        params : ExperimentParams object
            Contains config, number_of_pixels, and other parameters    
        data_folder : string
            path to the folder with the spooled series data, and the background image
        background_file_name : string
            name of background image, assumed to be in the data_folder
       
        Returns
        -------
        4D array of integers giving the background-subtracted camera counts in each pixel.
        Format: images[iterationNumber, pictureNumber, row, col]
    
        """
        background_array = np.zeros(params.number_of_pixels)
        #Load background image into background_array
        if background_file_name:
            background_img = data_folder + "//" + background_file_name
            file=open(background_img,"rb")
            content=file.read()
            background_array = np.frombuffer(content, dtype=params.data_type)
            background_array = background_array[0:params.number_of_pixels]
            file.close()

        #read the whole kinetic series, bg correct, and load all images into a numpy array called image-array_correcpted
        image_array = np.zeros(shape = (1, params.number_of_pixels * params.number_of_pics))[0] 
        image_array_corrected = np.zeros(shape = (1, params.number_of_pixels * params.number_of_pics))[0]
        for x in range(params.number_of_pics): 
            filename = data_folder + "\\" + root_filename + str(x+1)+ ".dat"    
            file = open(filename,"rb")
            content = file.read()
            data_array = np.frombuffer(content, dtype=params.data_type)
            data_array = data_array[0:params.number_of_pixels]
            data_array_corrected = data_array - background_array 
            image_array[x*params.number_of_pixels: (x+1)*params.number_of_pixels] = data_array
            # print("max value before background subtraction = "+str(np.max(image_array)))
            image_array_corrected[x*params.number_of_pixels: (x+1)*params.number_of_pixels] = data_array_corrected
            #print("max value after background subtraction = "+str(np.max(image_array_corrected)))
            
        # reshape the total_image_array_corrected into a 4D array
        # outermost dimension's size is equal to the number of iterations, 
        # 2nd outer dimensions size is number of pictures per iteration
        # 3rd dimensions size is equal to the height of the images
        #print(params.number_of_iterations, params.picturesPerIteration, params.height, params.width)
        images = np.reshape(image_array_corrected,(params.number_of_iterations, params.picturesPerIteration, params.height, params.width))
        return images
    
def LoadVariableLog(path):
    if not os.path.exists(path):
        print('The path for variable logs does not exist, no logs were loded.')
        return None
        
    filenames = os.listdir(path)
    filenames.sort()
    
    variable_list = []
    
    for filename in filenames:
        variable_dict = {}
        variable_dict['time'] = datetime.datetime.fromtimestamp( os.path.getctime(os.path.join(path,filename)) )
        
        # datetime.datetime.strptime(filename, 'Variables_%Y_%m_%d_%H_%M_%S_0.txt')
        # print(parameter_dict['time'])
        with open( path + '/' + filename) as f:
            next(f)
            for line in f:
                key, val = line.strip().split(' = ')
                variable_dict[key.replace(' ', '_')] = float(val)
                
        variable_list.append(variable_dict)
        
    return pd.DataFrame(variable_list).set_index('time')
    
# def GetVariables(variables, timestamp, variableLog):
#     variableSeries = variableLog[ variableLog.time < timestamp ].iloc[-1]
    
#     return variableSeries[variables]


def VariableFilter(timestamps, variableLog, variableFilterList):    
    
    # return all( [ eval( 'variableLogItem.' + ii ) for ii in variableFilterList ] )
    
    filteredList = []
    for ii, tt in enumerate(timestamps):        
        satisfy = []                                                
        for jj in variableFilterList:
            # print(eval('variableLogItem.'+ii ))
            satisfy.append( eval('variableLog.loc[tt].' + jj.replace(' ','_')) ) 
            
        if not all(satisfy):
            filteredList.append(ii)
        
    return filteredList

def Filetime2Logtime(fileTime, variableLog, timeLowLim=2, timeUpLim=18):
    if variableLog is None:
        return []
    
    Index = variableLog.index
    logTimes = []
    for ii, t in enumerate(fileTime):
        logTime = Index[ Index <= t ][-1]        
        dt = (t - logTime).total_seconds()
        
        if dt > timeUpLim or dt < timeLowLim:
            print('Warning! The log is {:.2f} s earlier than the data file, potential mismatching!'.format(dt))
            
            if dt < timeLowLim:
                logTime = Index[ Index <= t ][-2]
                print('Picked the logfile earlier, the time interval is {:.2f} s'.format((t - logTime).total_seconds()))

        logTimes.append(logTime)
        
    return logTimes









def GetFilePaths(*paths, picsPerIteration=3, examFrom=None, examUntil=None):
    '''
    Generate the list of filenames in the correct order and selected range
    used for loading Zyla images. 
    '''
    FilePaths = []
    
    for path in paths:
    
        filenames = glob.glob1(path,"*spool.dat")
        filenamesInd = [ ii[6::-1] for ii in filenames]
    
        indexedFilenames = list(zip(filenamesInd, filenames))
        indexedFilenames.sort()
    
        filepaths = [os.path.join(path, ii[1]) for ii in indexedFilenames]
        FilePaths.extend(filepaths)
    
    if examFrom:
        examFrom *= picsPerIteration
    if examUntil:
        examUntil *= picsPerIteration
        
    return FilePaths[examFrom: examUntil]

def LoadSpooledSeriesV2(*paths, picturesPerIteration=3, 
                        background_folder = ".",  background_file_name= "",
                        examFrom=None, examUntil=None, return_fileTime=0):
        """
        Modified from LoadSpooledSeries, works with multiple folders. 
        
        Parameters
        ----------
        paths : string
            path to the folder with the spooled series data, and the background image
        background_file_name : string
            name of background image, assumed to be in the data_folder
       
        Returns
        -------
        4D array of integers giving the background-subtracted camera 
        in each pixel.
        Format: images[iterationNumber, pictureNumber, row, col]
    
        """
        
        for path in paths:
            if not os.path.exists(path):
                raise Exception("Data folder not found:" + str(path))
        
            number_of_pics = len(glob.glob1(path,"*spool.dat"))
            if number_of_pics == 0:
                print('Warning!\n{}\ndoes not contain any data file!'.format(path))
            elif number_of_pics % picturesPerIteration:
                raise Exception('The number of data files in\n{}\nis not correct!'.format(path))
            
        #Load meta data
        metadata = LoadConfigFile(paths[0], "acquisitionmetadata.ini",encoding="utf-8-sig")
        height =int( metadata["data"]["AOIHeight"])
        width = int( metadata["data"]["AOIWidth"])
        pix_format = metadata["data"]["PixelEncoding"]
        if pix_format.lower() == "mono16":
            data_type=np.uint16
        else:
            raise Exception("Unknown pixel format " + pix_format)
        number_of_pixels = height*width
                
        #Get the filenames and select the range needed.
        filePaths = GetFilePaths(*paths, picsPerIteration=picturesPerIteration, 
                                 examFrom=examFrom, examUntil=examUntil)
        number_of_pics = len(filePaths)        
        number_of_iterations = int(number_of_pics/picturesPerIteration)
        
        #Load background image into background_array
        if background_file_name:
            background_img = os.path.join(background_folder, background_file_name)
            file=open(background_img,"rb")
            content=file.read()
            background_array = np.frombuffer(content, dtype=data_type)
            background_array = background_array[0:number_of_pixels]
            file.close()
        #read the whole kinetic series, bg correct, and load all images into a numpy array called image-array_correcpted
        image_array = np.zeros(shape = (number_of_pixels * number_of_pics))
        
        fileTime = []
        fileFolder = []
        
        for ind, filepath in enumerate(filePaths):
            
            if ind % picturesPerIteration == 0 and return_fileTime:
                fileTime.append( datetime.datetime.fromtimestamp( os.path.getctime(filepath) ) )
                fileFolder.append( '/'.join(filepath.replace('\\', '/').rsplit('/', 4)[1:-1]) )
            
            file = open(filepath, "rb")
            content = file.read()
            data_array = np.frombuffer(content, dtype=data_type)
            data_array = data_array[:number_of_pixels] # a spool file that is not bg corrected
            if background_file_name:
                data_array = data_array - background_array #spool file that is background corrected
            image_array[ind*number_of_pixels: (ind+1)*number_of_pixels] = data_array            

        # reshape the total_image_array_corrected into a 4D array
        # outermost dimension's size is equal to the number of iterations, 
        # 2nd outer dimensions size is number of pictures per iteration
        # 3rd dimensions size is equal to the height of the images
        #print(params.number_of_iterations, params.picturesPerIteration, params.height, params.width)
        images = image_array.reshape(number_of_iterations, picturesPerIteration, height, width)
        
        return images, fileTime, fileFolder
    
    
def PreprocessZylaImg(*paths, examFrom=None, examUntil=None, rotateAngle=1,
                      subtract_burntin=0, skipFirstImg=1, 
                      loadVariableLog=1, dirLevelAfterDayFolder=2):

    pPI = 4 if (subtract_burntin or skipFirstImg) else 3
    firstFrame = 1 if (skipFirstImg and not subtract_burntin) else 0   
    
    print('first frame is', firstFrame)
    
    rawImgs, fileTime, fileFolder = LoadSpooledSeriesV2(*paths, picturesPerIteration=pPI, 
                                                        return_fileTime=loadVariableLog, 
                                                        examFrom=examFrom, examUntil=examUntil)
    
    _, _, _, columnDensities, _, _ = absImagingSimple(rawImgs, firstFrame=firstFrame, correctionFactorInput=1.0,
                                                      subtract_burntin=subtract_burntin, preventNAN_and_INF=True)
    
    variableLog = None
    if loadVariableLog:
        dayfolders = np.unique( [ii.replace('\\', '/').rstrip('/').rsplit('/', dirLevelAfterDayFolder)[0] for ii in paths] )

        variableLog = []
        for ff in dayfolders:
            variablelogfolder = os.path.join(ff, 'Variable Logs')
            variableLog.append( LoadVariableLog(variablelogfolder) )
            
        variableLog = pd.concat(variableLog)
        logTime = Filetime2Logtime(fileTime, variableLog)
        variableLog = variableLog.loc[logTime]
        variableLog.insert(0, 'Folder', fileFolder)
    
    return rotate(columnDensities, rotateAngle, axes=(1,2), reshape = False), variableLog        


def GetFileNames(data_folder, picsPerIteration=3, examFrom=None, examUntil=None):
    '''
    Generate the list of filenames in the correct order and selected range
    used for loading Zyla images. 
    '''
    filenames = glob.glob1(data_folder,"*spool.dat")
    filenamesInd = [ ii[6::-1] for ii in filenames]
    
    indexedFilenames = list(zip(filenamesInd, filenames))
    indexedFilenames.sort()
    
    filenames = [ii[1] for ii in indexedFilenames]
    
    if examFrom:
        examFrom *= picsPerIteration
    if examUntil:
        examUntil *= picsPerIteration
        
    return filenames[examFrom: examUntil]

def LoadSpooledSeries(params, data_folder= "." ,background_folder = ".",  background_file_name= "",
                      examFrom=None, examUntil=None, return_fileTime=0):
        """
        Parameters
        ----------
        params : ExperimentParams object
            Contains picturesPerIteration    
        data_folder : string
            path to the folder with the spooled series data, and the background image
        background_file_name : string
            name of background image, assumed to be in the data_folder
       
        Returns
        -------
        4D array of integers giving the background-subtracted camera 
        in each pixel.
        Format: images[iterationNumber, pictureNumber, row, col]
    
        """
        if not os.path.exists(data_folder):
            raise Exception("Data folder not found:" + str(data_folder))
        #Load meta data
        metadata = LoadConfigFile(data_folder, "acquisitionmetadata.ini",encoding="utf-8-sig")
        height =int( metadata["data"]["AOIHeight"])
        width = int( metadata["data"]["AOIWidth"])
        pix_format = metadata["data"]["PixelEncoding"]
        if pix_format.lower() == "mono16":
            data_type=np.uint16
        else:
            raise Exception("Unknown pixel format " + pix_format)
        number_of_pixels = height*width
        
        number_of_pics = len(glob.glob1(data_folder,"*spool.dat"))
        picturesPerIteration = params.picturesPerIteration
        assert number_of_pics % picturesPerIteration == 0
        
        #Get the filenames and select the range needed.
        fileNames = GetFileNames(data_folder, picturesPerIteration, examFrom, examUntil)
        number_of_pics = len(fileNames)        
        number_of_iterations = int(number_of_pics/picturesPerIteration)

        background_array = np.zeros(number_of_pixels)
        #Load background image into background_array
        if background_file_name:
            background_img = background_folder + "//" + background_file_name
            file=open(background_img,"rb")
            content=file.read()
            background_array = np.frombuffer(content, dtype=data_type)
            background_array = background_array[0:number_of_pixels]
            file.close()
        #read the whole kinetic series, bg correct, and load all images into a numpy array called image-array_correcpted
        image_array =           np.zeros(shape = (number_of_pixels * number_of_pics))
        image_array_corrected = np.zeros(shape = (number_of_pixels * number_of_pics))
        fileTime = []
        
        for ind in range(number_of_pics): 
            
            filename = data_folder + "\\" + fileNames[ind] 
                
            if ind % picturesPerIteration == 0 and return_fileTime:
                fileTime.append( datetime.datetime.fromtimestamp( os.path.getctime(filename) ) )
            
            file = open(filename,"rb")
            content = file.read()
            data_array = np.frombuffer(content, dtype=data_type)
            data_array = data_array[0:number_of_pixels] # a spool file that is not bg corrected
            data_array_corrected = data_array - background_array #spool file that is background corrected
            image_array[ind*number_of_pixels: (ind+1)*number_of_pixels] = data_array
            # print("max value before background subtraction = "+str(np.max(data_array)))
            image_array_corrected[ind*number_of_pixels: (ind+1)*number_of_pixels] = data_array_corrected
            #print("max value after background subtraction = "+str(np.max(image_array_corrected)))
            

            
        # reshape the total_image_array_corrected into a 4D array
        # outermost dimension's size is equal to the number of iterations, 
        # 2nd outer dimensions size is number of pictures per iteration
        # 3rd dimensions size is equal to the height of the images
        #print(params.number_of_iterations, params.picturesPerIteration, params.height, params.width)
        images = np.reshape(image_array_corrected,(number_of_iterations, picturesPerIteration, height, width))
        
        if return_fileTime:
            return images, fileTime
        else:
            return images
    
def LoadFromSpooledSeries(params, iterationNum, data_folder= "." ,background_folder = ".",  background_file_name= ""):
        """
        Parameters
        ----------
        params : ExperimentParams object
            Contains picturesPerIteration    
        data_folder : string
            path to the folder with the spooled series data, and the background image
        background_file_name : string
            name of background image, assumed to be in the data_folder
       
        Returns
        -------
        4D array of integers giving the background-subtracted camera 
        in each pixel.
        Format: images[iterationNumber, pictureNumber, row, col]
    
        """
        number_of_pics = len(glob.glob1(data_folder,"*spool.dat"))
        if iterationNum == -1:
            numPicsDividesThree = int(np.floor(number_of_pics/3)*3)
            startNum = numPicsDividesThree-3
        else:
            startNum = iterationNum*params.picturesPerIteration
        numToLoad = params.picturesPerIteration
        #Load meta data
        metadata = LoadConfigFile(data_folder, "acquisitionmetadata.ini",encoding="utf-8-sig")
        height =int( metadata["data"]["AOIHeight"])
        width = int( metadata["data"]["AOIWidth"])
        pix_format = metadata["data"]["PixelEncoding"]
        if pix_format.lower() == "mono16":
            data_type=np.uint16
        else:
            raise Exception("Unknown pixel format " + pix_format)
        number_of_pixels = height*width
        picturesPerIteration = params.picturesPerIteration
        assert numToLoad % picturesPerIteration == 0
        number_of_iterations = int(numToLoad/picturesPerIteration)

        background_array = np.zeros(number_of_pixels)
        #Load background image into background_array
        if background_file_name:
            background_img = background_folder + "//" + background_file_name
            file=open(background_img,"rb")
            content=file.read()
            background_array = np.frombuffer(content, dtype=data_type)
            background_array = background_array[0:number_of_pixels]
            file.close()
        #read the whole kinetic series, bg correct, and load all images into a numpy array called image-array_correcpted
        image_array =           np.zeros(shape = (number_of_pixels * numToLoad))
        image_array_corrected = np.zeros(shape = (number_of_pixels * numToLoad))
        spool_number = '0000000000'
        for x in np.arange(startNum,startNum+numToLoad): 
            localIndex = x - startNum
            filename = data_folder + "\\"+ str(int(x))[::-1] + spool_number[0:(10-len(str(int(x))))]+"spool.dat"
            file = open(filename,"rb")
            content = file.read()
            data_array = np.frombuffer(content, dtype=data_type)
            data_array = data_array[0:number_of_pixels] # a spool file that is not bg corrected
            data_array_corrected = data_array - background_array #spool file that is background corrected
            image_array[localIndex*number_of_pixels: (localIndex+1)*number_of_pixels] = data_array
            # print("max value before background subtraction = "+str(np.max(data_array)))
            image_array_corrected[localIndex*number_of_pixels: (localIndex+1)*number_of_pixels] = data_array_corrected
            #print("max value after background subtraction = "+str(np.max(image_array_corrected)))
            
        # reshape the total_image_array_corrected into a 4D array
        # outermost dimension's size is equal to the number of iterations, 
        # 2nd outer dimensions size is number of pictures per iteration
        # 3rd dimensions size is equal to the height of the images
        #print(params.number_of_iterations, params.picturesPerIteration, params.height, params.width)
        images = np.reshape(image_array_corrected,(number_of_iterations, picturesPerIteration, height, width))
        return images    
    
    
    
    

def PreprocessZylaPictures(dataRootFolder, date, dataFolder, subtract_burntin=0, rotateAngle=1,
                           examNum=None, examFrom=None, repetition=1, return_fileTime=0,
                           variableFilterList=[], pictureToHide=None):  
        
    dayfolder = GetDataLocation(date, DataPath=dataRootFolder)
    dataFolder = os.path.join(dayfolder, dataFolder)
    variableLog_folder = os.path.join(dayfolder, 'Variable Logs')
    examFrom, examUntil = GetExamRange(examNum, examFrom, repetition)
    
    pPI = 4 if subtract_burntin else 3    
    params = ExperimentParams(date, t_exp = 10e-6, picturesPerIteration= pPI, cam_type = "zyla")

    images_array, fileTime = LoadSpooledSeries(params=params, data_folder=dataFolder, 
                                               return_fileTime=1, examFrom=examFrom, examUntil=examUntil)
    # images_array = images_array[examFrom: examUntil]
    # fileTime = fileTime[examFrom: examUntil]
    
    variableLog = LoadVariableLog(variableLog_folder)
    logTime = Filetime2Logtime(fileTime, variableLog)
        
    if variableFilterList and variableLog is not None:    
        filteredList = VariableFilter(logTime, variableLog, variableFilterList)
        images_array = np.delete(images_array, filteredList, 0)
        logTime = np.delete(logTime, filteredList, 0)
    
    if pictureToHide is not None:
        images_array = np.delete(images_array, pictureToHide, 0)
        if logTime is not None:
            logTime = np.delete(logTime, pictureToHide, 0)
    
    Number_of_atoms, N_abs, ratio_array, columnDensities, deltaX, deltaY = absImagingSimple(images_array, 
                    firstFrame=0, correctionFactorInput=1.0,  
                    subtract_burntin=subtract_burntin, preventNAN_and_INF=True)
    
    return rotate(columnDensities, rotateAngle, axes=(1,2), reshape = False), params, variableLog, logTime



def CountsToAtoms(params, counts):
    """
    Convert counts to atom number for fluorescence images
    
    Parameters
    ----------
    params : ExperimentParams object
        
    counts : array or number
        Camera counts from fluorescence image
        
    Returns
    -------
    Atom number (per pixel) array in same shape as input counts array

    """
    return  (4*np.pi*counts*params.camera.sensitivity)/(params.camera.quantum_eff*params.R_scat*params.t_exp*params.solid_angle)
    

def ShowImages3d(images,vmin=None,vmax=None):
    """
    Draws a grid of images

    Parameters
    ----------
    images : 3d Array

    """
    iterations, height, width = np.shape(images)
    #print(iterations,picturesPerIteration)
    #imax = np.max(images)
    #imin = np.min(images)
    MAX_COLS = 5
    ncols = min(MAX_COLS, iterations)
    nrows = int(np.ceil(iterations/ncols))
    fig =plt.figure()
    for it in range(iterations):
        #print(it)
        ax = plt.subplot(nrows,ncols,it+1)
        im = ax.imshow(images[it,:,:],cmap="gray",vmin = vmin, vmax=vmax)
        divider = make_axes_locatable(ax)
        cax = divider.append_axes('right', size='5%', pad=0.05)
        fig.colorbar(im, cax=cax, orientation='vertical')
    plt.tight_layout()
    plt.show()

def ShowImages(images):
    """
    Draws a grid of images

    Parameters
    ----------
    images : 4d Array

    """
    iterations, picturesPerIteration, height, width = np.shape(images)
    #print(iterations,picturesPerIteration)
    #imax = np.max(images)
    #imin = np.min(images)
    
    for it in range(iterations):
        for pic in range(picturesPerIteration):
            ax = plt.subplot(iterations, picturesPerIteration, it*picturesPerIteration + pic+1)
            ax.imshow(images[it,pic,:,:],cmap="gray")#,vmin = imin, vmax=imax)
    plt.tight_layout()
    plt.show()
    
def ShowImagesTranspose(images, logTime=None, variableLog=None,
                        variablesToDisplay=None, showTimestamp=False, 
                        uniformscale=False):
    """
    Draws a grid of images

    Parameters
    ----------
    images : 4d Array
    
    autoscale: boolean
        True: scale each image independently

    """
    
    iterations, picturesPerIteration, _, _ = images.shape
        
    if uniformscale:
        imax = images.max()
        imin = images.min()
    
    plt.rcParams.update({'font.size' : 8})
    
    fig, axs = plt.subplots(picturesPerIteration, iterations, figsize=(2.65*iterations, 2*picturesPerIteration), 
                            sharex=True, sharey=True, squeeze = False)
    plt.subplots_adjust(hspace=0.02, wspace=0.02)
    
    for it in range(iterations):
        for pic in range(picturesPerIteration):
            
            if uniformscale:                
                axs[pic, it].imshow(images[it,pic], cmap='gray', vmin = imin, vmax= imax)
            else:
                axs[pic, it].imshow(images[it,pic], cmap='gray')
                
            if variablesToDisplay is None or variableLog is None:
                axs[pic, it].text(0, 0, "iter #{}, pic #{}".format(it, pic), ha='left', va='top', 
                                  bbox=dict(boxstyle="square",ec=(0,0,0), fc=(1,1,1), alpha=0.7) )
            else:
                variablesToDisplay = [ii.replace(' ','_') for ii in variablesToDisplay]
                axs[pic, it].text(0,0, 
                                variableLog.loc[logTime[it]][variablesToDisplay].to_string(name=showTimestamp).replace('Name','Time'), 
                                fontsize=5, ha='left', va='top',
                                bbox=dict(boxstyle="square", ec=(0,0,0), fc=(1,1,1), alpha=0.7))
                
    fig.tight_layout()    
            

# simple, no analysis, list of pics => normalized
def ImageTotals(images):
    """
    
    ----------
    images : 4D array of images
    
    Returns
    -------
    2D Array of sums over the images

    """
    
    shape1 = np.shape(images)
    assert len(shape1) == 4, "input array must be 4D"
    
    shape2 = shape1[:-2]
    totals = np.zeros(shape2)
    
    for i in range(shape2[0]):
        for j in range(shape2[1]):
            totals[i,j] = np.sum(images[i,j,:,:])
    return totals
    
# def temp(images):    
#     atoms_x = np.zeros((params.number_of_pics, params.width))
#     atoms_y = np.zeros((params.number_of_pics, params.height))   
    
#     #Sum the columns of the region of interest to get a line trace of atoms as a function of x position
#     for i in range(params.number_of_iterations):
#         for j in range(params.picturesPerIteration) :
#             im_temp = images[i, j, params.ymin:params.ymax, params.xmin:params.xmax]
#             count_x = np.sum(im_temp,axis = 0) #sum over y direction/columns 
#             count_y = np.sum(im_temp,axis = 1) #sum over x direction/rows
#             atoms_x[i] = (4*np.pi*count_x*params.sensitivity)/(params.quantum_eff*params.R_scat*params.t_exp*params.solid_angle)
#             atoms_y[i] = (4*np.pi*count_y*params.sensitivity)/(params.quantum_eff*params.R_scat*params.t_exp*params.solid_angle)
#             print("num_atoms_vs_x in frame" , i, "is: {:e}".format(np.sum(atoms_x[i])))
#             print("num_atoms_vs_y in frame" , i, "is: {:e}".format(np.sum(atoms_y[i])))
    
#     if atoms_x != atoms_y:
#         print("atom count calculated along x and along y do NOT match")

#     atoms_x_max = max(atoms_x)
#     atoms_y_max = max(atoms_y)
#     atoms_max = max(atoms_x_max, atoms_y_max)        
    
#     return atoms_x, atoms_y, atoms_max        
#         #  output_array = np.array((number_of_iteration, outputPicsPerIteration, height, width)

def flsImaging(images, params=None, firstFrame=0, rowstart = 0, rowend = -1, columnstart =0, columnend = -1, subtract_burntin = False):
    '''
    Parameters
    ----------
    images : array
        4D array
    
    firstFrame : int
        which frame has the probe with atoms (earlier frames are thrown out)   
    '''
    if params:
        pixelsize=params.camera.pixelsize_microns*1e6
        magnification=params.magnification
    else:
        pixelsize=6.5e-6 #Andor Zyla camera
        magnification = 0.55 #75/125 (ideally) updated from 0.6 to 0.55 on 12/08/2022
    iteration, picsPerIteration, rows, cols = np.shape(images)
    columnDensities = np.zeros((iteration, rows, cols))
    Number_of_atoms = np.zeros((iteration))
    # subtracted = np.zeros((iteration, rows, cols))
    if params:
        pixelsize=params.camera.pixelsize_microns*1e6
        magnification=params.magnification
    else:
        pixelsize=6.5e-6 #Andor Zyla camera
        magnification = 0.55 #75/125 (ideally) updated from 0.6 to 0.55 on 12/08/2022    
    deltaX = pixelsize/magnification #pixel size in atom plane
    deltaY = deltaX
    for i in range(iteration):
        if (subtract_burntin):
            subtracted_array = images[i, firstFrame+1,:,:] - images[i, firstFrame,:,:]
        else:
            subtracted_array = images[i, firstFrame,:,:]
        columnDensities[i] = CountsToAtoms(params, subtracted_array)/deltaX/deltaY                                                                                       
        Number_of_atoms[i] = np.sum(columnDensities[i, rowstart:rowend, columnstart:columnend])*deltaX*deltaY
    return Number_of_atoms, columnDensities, deltaX, deltaY
   
     
#abs_img_data must be a 4d array
def absImagingSimple(abs_img_data, params=None, firstFrame=0, correctionFactorInput=1, 
                     rowstart = 0, rowend = -1, columnstart =0, columnend = -1, subtract_burntin = False,
                     preventNAN_and_INF = False):
    """
    Assume that we took a picture of one spin state, then probe without atoms, then dark field
    In total, we assume three picture per iteration

    Parameters
    ----------
    images : array
        4D array
    
    firstFrame : int
        which frame has the probe with atoms (earlier frames are thrown out)
    Returns
    -------
    signal : array
        4D array, with one image per run of the experiment

    """
    iteration, picsPerIteration, rows, cols = np.shape(abs_img_data)
    
    ratio_array = np.zeros((iteration, rows, cols), dtype=np.float64)
    columnDensities = np.zeros((iteration, rows, cols))
    N_abs = np.zeros((iteration))
    Number_of_atoms = np.zeros((iteration))
    
    if params:
        pixelsize=params.camera.pixelsize_microns*1e6
        magnification=params.magnification
    else:
        pixelsize=6.5e-6 #Andor Zyla camera
        magnification = 0.55 #75/125 (ideally) updated from 0.6 to 0.55 on 12/08/2022
        
    for i in range(iteration):
        # print("dimensions of the data for testing purposes:", np.shape(abs_img_data))
        # subtracted1 = abs_img_data[i,0,:,:] - abs_img_data[i,2,:,:]
        # subtracted2 = abs_img_data[i,1,:,:] - abs_img_data[i,2,:,:]
        if (subtract_burntin):
            subtracted1 = abs_img_data[i,firstFrame+1,:,:] - abs_img_data[i,firstFrame+0,:,:]   
            subtracted2 = abs_img_data[i,firstFrame+2,:,:] - abs_img_data[i,firstFrame+3,:,:]
        else:
            subtracted1 = abs_img_data[i,firstFrame+0,:,:] - abs_img_data[i,firstFrame+2,:,:]
            subtracted2 = abs_img_data[i,firstFrame+1,:,:] - abs_img_data[i,firstFrame+2,:,:]
        
        if (preventNAN_and_INF):
            #if no light in first image
            subtracted1[ subtracted1<= 0 ] = 1
            subtracted2[ subtracted1<= 0 ] = 1
            
            #if no light in second image
            subtracted1[ subtracted2<= 0] = 1
            subtracted2[ subtracted2<= 0] = 1
            
        ratio = subtracted1 / subtracted2
        
        if correctionFactorInput:
            correctionFactor = correctionFactorInput
        else:
            correctionFactor = np.mean(ratio[-5:][:])
        
        # print("correction factor iteration", i+1, "=",correctionFactor)
        ratio /= correctionFactor #this is I/I0
        ratio_array[i] = ratio
        opticalDensity = -1 * np.log(ratio)
        N_abs[i] = np.sum(opticalDensity) 
        detuning = 2*np.pi*0 #how far from max absorption @231MHz. if the imaging beam is 230mhz then delta is -1MHz. unit is Hz
        linewidth = 36.898e6 #units Hz
        wavevector =2*np.pi/(671e-9) #units 1/m
        cross_section = (6*np.pi / (wavevector**2)) * (1+(2*detuning/linewidth)**2)**-1 
        n2d = opticalDensity / cross_section
        #n2d[~np.isfinite(columnDensities)] = 0
        deltaX = pixelsize/magnification #pixel size in atom plane
        deltaY = deltaX
        Number_of_atoms[i] = np.sum(n2d[rowstart:rowend][columnstart:columnend]) * deltaX * deltaY
        # print("number of atoms iteration", i+1, ": ", Number_of_atoms[i]/1e6,"x10^6")
        columnDensities[i] = n2d
    return Number_of_atoms, N_abs, ratio_array, columnDensities, deltaX, deltaY
    
    # iterations, picturesPerIteration, height, width = np.shape(images)
    
    # signal = np.zeros((iterations,1, height, width))
    
    # if picturesPerIteration==4:
    #     for i in range(iterations-1):
    #         # signal is column density along the imaging path
    #         signal[i,0,:,:] = (images[i,1,:,:] - images[i,3,:,:]) / (images[i,2,:,:] - images[i,3,:,:])
    # else:
    #     print("This spooled series does not have the correct number of exposures per iteration for Absorption Imaging")        
        
    # return signal



def integrate1D(array2D, dx=1, free_axis="y"):
    #free_axis is the axis that remains after integrating
    if free_axis == 'x':
        axis = 0
    elif free_axis == 'y':
        axis = 1
    array1D = np.sum(array2D, axis = axis)*dx
    return array1D


def Gaussian(x, amp, center, w, offset=0):
    return amp * np.exp(-0.5*(x-center)**2/w**2) + offset

def MultiGaussian(x, *params):
    L = len(params)        
    if  L % 3 != 1:
        raise TypeError('The number of parameters provided to MultiGaussian() besides x variable should be 3N+1, N is the number of Gaussian curves.')

    result = np.zeros(len(x))
    N = L//3
    
    for n in range(N):
        result += Gaussian(x, *params[n:-1:N])
        # print(params[n:-1:N])
    return result + params[-1]


def fitbg(data, signal_feature='narrow', signal_width=10, fitbgDeg=5): 
       
    datalength = len(data)
    signalcenter = data.argmax()
    datacenter = int(datalength/2)    
    xdata = np.arange(datalength)
    
    if signal_feature == 'wide':
        mask_hw = int(datalength/3)
        bg_mask = np.full(xdata.shape, True)
        bg_mask[signalcenter - mask_hw: signalcenter + mask_hw] = False  
        
        p = np.polyfit( xdata[bg_mask], data[bg_mask], deg=2 )        
        
    else:
        mask_hw = int(datalength/signal_width)
        bg_mask = np.full(xdata.shape, True)
        center_mask = bg_mask.copy()
        bg_mask[signalcenter - mask_hw: signalcenter + mask_hw] = False  
        center_mask[datacenter - mask_hw : datacenter + mask_hw] = False        
        bg_mask = bg_mask * center_mask
        bg_mask[:mask_hw] = True
        bg_mask[-mask_hw:] = True
        
        p = np.polyfit( xdata[bg_mask], data[bg_mask], deg=fitbgDeg )
    
    return np.polyval(p, xdata)
    
    
    
def fitgaussian1D(data , xdata=None, dx=1, doplot = False, 
                  subtract_bg=True, signal_feature='narrow', 
                  label="", title="", newfig=True, 
                  xlabel="", ylabel="", xscale_factor=1, legend=False,
                  yscale_factor=1):
    
    if subtract_bg:
        bg = fitbg(data, signal_feature=signal_feature) 
        originalData = data.copy()
        data = data - bg
        
        offset_g = 0
    else:
        offset_g = offset_g = min( data[:10].mean(), data[-10:].mean() )
    
    datalength = len(data)
    
    if xdata is None:
        xdata = np.arange( datalength )*dx  
        
    #initial guess:
    amp_g = data.max()
    center_g = xdata[ data.argmax() ]    
    w_g = ( data > 0.6*data.max() ).sum() * dx / 2
    
    guess = [amp_g, center_g, w_g, offset_g]
    
    try:
        popt, pcov = curve_fit(Gaussian, xdata, data, p0=guess, bounds=([-np.inf, -np.inf, 0, -np.inf],[np.inf]*4) )
    except Exception as e:
        print(e)
        return None  
 
    #      
    if doplot:
        if newfig:
            plt.figure()            
        if subtract_bg:                
            plt.plot(xdata*xscale_factor, originalData*yscale_factor, '.', label="{} data".format(label))
            plt.plot(xdata*xscale_factor, (Gaussian(xdata,*popt)+bg) * yscale_factor, label="{} fit".format(label))
            plt.plot(xdata*xscale_factor, bg*yscale_factor, '.', markersize=0.3)
            # ax.plot(xdata*xscale_factor, (Gaussian(xdata,*guess)+bg) * yscale_factor, label="{} fit".format(label))
        else:
            plt.plot(xdata*xscale_factor, data*yscale_factor, '.', label="{} data".format(label))
            plt.plot(xdata*xscale_factor, Gaussian(xdata,*popt) * yscale_factor, label="{} fit".format(label))

    if doplot:
        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        if legend:
            plt.legend()
    return popt

def fitgaussian2(array, dx=1, do_plot = False, title="",xlabel1D="",ylabel1D="", vmax=None, 
                 xscale_factor=1, yscale_factor=1, legend=False, title2D="", new_figure=True,num_rows=1,row=0):
    if do_plot:
        plt.rcParams.update({'font.size' : 10})
        if new_figure:
            plt.figure(figsize=(8,1.9*num_rows))
        #plt.title(title)
        
    popts=[]
    for ind, ax in enumerate(["x","y"]):
        array1D = integrate1D(array,dx, free_axis=ax)
        if do_plot:
            plt.subplot(num_rows,3,ind+2 + 3*row)
        ylabel= ylabel1D if ind==0 else ""
        popt= fitgaussian1D(array1D, dx=dx, doplot=do_plot, label=ax, title=title+" vs "+ax, newfig=False,
                            xlabel=xlabel1D, ylabel=ylabel, xscale_factor=xscale_factor, 
                            yscale_factor=yscale_factor, legend=legend)
        popts.append(popt) 
    if do_plot:
        plt.subplot(num_rows,3,1+3*row)
        plt.imshow(array, cmap = 'jet',vmin=0,vmax=vmax)
        #plt.colorbar()
        plt.xlabel("pixels")
        plt.ylabel("pixels")
        plt.title(title2D)
        plt.tight_layout()
        
    return popts[0], popts[1]


def DetectPeaks(yy, amp=1, width=3, denoise=0, doPlot=0):
    
    yycopy = yy.copy()
    
    if denoise:
        yycopy = gaussian_filter1d(yy, 3)
    
    # Determine the background with the otsu method and set to 0.
    # thr = threshold_otsu(yycopy)
    thr = 0.1 * (yy.max() - yy.min()) + yy.min()
    yycopy[yycopy < thr] = yy.min()    

    peaks, properties = signal.find_peaks(yycopy, prominence=amp*0.01*(yycopy.max()-yycopy.min()), width=width)

    if doPlot:
        fig, ax = plt.subplots(1,1, layout='constrained')
        
        ymin = yy[peaks] - properties["prominences"]
        ymax = yy[peaks]
        amp = ymax - ymin
        xmin = properties["left_ips"]
        xmax = properties["right_ips"]
        width = (xmax - xmin) / 2
        ax.vlines(x=peaks, ymin=ymin, ymax=ymax, color = "C1")
        ax.hlines(y=properties["width_heights"], xmin=xmin, xmax=xmax, color = "C1")
        xx = np.arange(len(yy))
        ax.plot(xx, MultiGaussian(xx, *amp, *peaks, *width, yy.min()))
        ax.plot(yy, '--')
        ax.plot(yycopy, '.g')

    return peaks, properties



def fitSingleGaussian(data, xdata=None, dx=1, 
                      subtract_bg=0, signal_feature='wide', 
                      signal_width=10, fitbgDeg=5,
                                          ):
    
    if subtract_bg:
        bg = fitbg(data, signal_feature=signal_feature, signal_width=signal_width, fitbgDeg=fitbgDeg) 
        data = data - bg        
        offset = 0
    else:
        offset = min( data[:10].mean(), data[-10:].mean() )
        bg = None
        
    if xdata is None:
        xdata = np.arange( len(data) )
        
    #initial guess:
    amp = data.max()
    center = xdata[ data.argmax() ]    
    w = ( data > 0.6*data.max() ).sum() * dx / 2
    
    guess = [amp, center, w, offset]
    
    try:
        popt, _ = curve_fit(Gaussian, xdata, data, p0 = guess, bounds=([-np.inf, -np.inf, 0, -np.inf],[np.inf]*4) )
        
    except Exception as e:
        print(e)
        return None
    
    popt[1:-1] *= dx
    
    return popt, bg
    

def fitMultiGaussian(data, xdata=None, dx=1, NoOfModel='auto', 
                     subtract_bg=0, signal_feature='wide', signal_width=10, fitbgDeg=5,
                     amp=1, width=3, denoise=0):
    
    if subtract_bg:
        bg = fitbg(data, signal_feature=signal_feature, signal_width=signal_width, fitbgDeg=fitbgDeg) 
        data = data - bg        
        offset = 0
    else:
        offset = min( data[:10].mean(), data[-10:].mean() )
        bg = None
    
    peaks, properties = DetectPeaks(data, amp, width, denoise, doPlot=0)
    
    #initial guess:
    amps = properties['width_heights'] + properties['prominences'] / 2
    widths = (properties['right_ips'] - properties['left_ips']) / 2    
    
    N = len(peaks)
    # print(peaks)
    if NoOfModel != 'auto' and NoOfModel > N:
        D = NoOfModel - N
        N = NoOfModel
        amps = np.concatenate( (amps, [amps.mean()]*D) )
        peaks = np.concatenate( (peaks, [int(amps.mean()-20)]*D) )
        widths = np.concatenate( (widths, [int(widths.mean())]*D) )
        
    # print(amps)
    # print(peaks)
    # print(widths)
    # print(offset)


    guess = [*amps, *peaks, *widths, offset]
    
    if xdata is None:
        xdata = np.arange( len(data) )
    
    try:
        # minamps = 0.1*(data.max()-data.min())
        minamps = 0
        popt, _ = curve_fit(MultiGaussian, xdata, data, p0 = guess,
                            bounds=([minamps]*N + [0]*N + [3]*N + [-np.inf], [np.inf]*(3*N+1)))
        
    except Exception as e:
        print(e)
        return None, None
    
    popt[N:-1] *= dx
    
    return popt, bg


def fitgaussian1D_June2023(data , xdata=None, dx=1, doplot = False, ax=None, 
                           subtract_bg = True, signal_feature = 'wide', 
                           signal_width=10, fitbgDeg=5,
                           add_title = False, add_xlabel=False, add_ylabel=False, no_xticklabel=True,
                           label="", title="", newfig=True, xlabel="", ylabel="", 
                           xscale_factor=1, legend=False, yscale_factor=1):
    
    if subtract_bg:
        bg = fitbg(data, signal_feature=signal_feature, signal_width=signal_width, fitbgDeg=fitbgDeg) 
        originalData = data.copy()
        data = data - bg        
        
        offset_g = 0
    else:
        offset_g = min( data[:10].mean(), data[-10:].mean() )
    
    datalength = len(data)
    
    if xdata is None:
        xdata = np.arange( datalength ) * dx  
        
    #initial guess:
    amp_g = data.max()
    center_g = xdata[ data.argmax() ]    
    w_g = ( data > 0.6*data.max() ).sum() * dx / 2
    
    guess = [amp_g, center_g, w_g, offset_g]
    
    try:
        popt, pcov = curve_fit(Gaussian, xdata, data, p0 = guess, bounds=([-np.inf, -np.inf, 0, -np.inf],[np.inf]*4) )
        
    except Exception as e:
        print(e)
        return None  
          
    if doplot:
        if subtract_bg:                
            ax.plot(xdata*xscale_factor, originalData*yscale_factor, '.', label="{} data".format(label))
            ax.plot(xdata*xscale_factor, (Gaussian(xdata,*popt)+bg) * yscale_factor, label="{} fit".format(label))
            ax.plot(xdata*xscale_factor, bg*yscale_factor, '.', markersize=0.3)
            # ax.plot(xdata*xscale_factor, (Gaussian(xdata,*guess)+bg) * yscale_factor, label="{} fit".format(label))
        else:
            ax.plot(xdata*xscale_factor, data*yscale_factor, '.', label="{} data".format(label))
            ax.plot(xdata*xscale_factor, Gaussian(xdata,*popt) * yscale_factor, label="{} fit".format(label))
            
        ax.ticklabel_format(axis='both', style='sci', scilimits=(-3,3))
        ax.tick_params('y', direction='in', pad=-5)
        plt.setp(ax.get_yticklabels(), ha='left')
        
        if add_title:
            ax.set_title(title)
        if add_xlabel:
            ax.set_xlabel(xlabel)
        if add_ylabel:
            ax.set_ylabel(ylabel)            
        if no_xticklabel == True:
            ax.set_xticklabels([])
        if legend:
            ax.legend()
    return popt

#Modified from fitgaussian2, passing the handle for plotting in subplots. 
def fitgaussian2D(array, dx=1, do_plot=False, ax=None, fig=None, Ind=0, imgNo=1, 
                  subtract_bg = True, signal_feature = 'wide', 
                  signal_width=10, fitbgDeg=5,
                  vmax = None, vmin = 0,
                  title="", title2D="", 
                  xlabel1D="",ylabel1D="",
                  xscale_factor=1, yscale_factor=1, legend=False):
    
    add_title = False
    add_xlabel=False
    add_ylabel=False
    no_xticklabel=True
    
    if do_plot:
        if ax is None:#Create fig and ax if it is not passed.
            fig, ax = plt.subplots(1,3, figsize=(8,2))
            plt.rcParams.update({'font.size' : 10})
        else:
            plt.rcParams.update({'font.size' : 8})
        
        #Add colorbar
        im = ax[0].imshow(array, cmap = 'jet',vmin=vmin,vmax=vmax)
        if fig:
            divider = make_axes_locatable(ax[0])
            cax = divider.append_axes('right', size='3%', pad=0.05)
            fig.colorbar(im, cax=cax, orientation='vertical')
        
        if Ind == 0:
            ax[0].set_title(title2D)
            add_title = True            
        if Ind+1 == imgNo:
            ax[0].set_xlabel("pixels")
            add_xlabel = True
            no_xticklabel = False
        if Ind == int(imgNo/2):
            ax[0].set_ylabel("pixels")
            add_ylabel = True
        if no_xticklabel == True:
            ax[0].set_xticklabels([])
    else:
        ax = [None] * 3
        
    popts=[]
    for ind, axis in enumerate(["x","y"]):
        array1D = integrate1D(array, dx, free_axis=axis)        
        popt= fitgaussian1D_June2023(array1D, dx=dx, doplot=do_plot, ax=ax[ind+1], 
                                     subtract_bg = subtract_bg, signal_feature = signal_feature, 
                                     signal_width=signal_width, fitbgDeg=fitbgDeg,
                                     add_title = add_title, add_xlabel=add_xlabel, add_ylabel=add_ylabel, no_xticklabel=no_xticklabel,
                                     label=axis, title=title+" vs "+axis, newfig=False,
                                     xlabel=xlabel1D, ylabel=ylabel1D, xscale_factor=xscale_factor, 
                                     yscale_factor=yscale_factor, legend=legend)
        popts.append(popt) 
    return popts[0], popts[1]


def fitgaussian(array, do_plot = False, vmax = None,title="", 
                logTime=None, variableLog=None,
                count=None, variablesToDisplay=None, showTimestamp=False,
                save_column_density = False, column_density_xylim = None): 
    #np.sum(array, axis = 0) sums over rows, axis = 1 sums over columns
    rows = np.linspace(0, len(array), len(array))
    cols = np.linspace(0, len(array[0]), len(array[0]))
    row_sum = np.sum(array, axis = 0)  
    col_sum = np.sum(array, axis = 1)
    # print("rows = "+str(rows))
    # print("np.shape(array) = "+str(np.shape(array)))
    # print("np.shape(rows) = "+str(np.shape(rows)))
    # print("np.shape(cols) = "+str(np.shape(cols)))
    # print("np.shape(row_sum) = "+str(np.shape(row_sum)))
    # print("np.shape(col_sum) = "+str(np.shape(col_sum)))
    ampx = np.max(row_sum)
    centerx = np.argmax(row_sum)
    wx = len(rows)/12
    # offsetx = row_sum[0]
    ampy = np.max(col_sum)
    centery = np.argmax(col_sum)
    wy = len(cols)/12
    
    widthx, center_x, widthy, center_y = np.nan, np.nan, np.nan, np.nan
    try:
        poptx, pcovx = curve_fit(Gaussian, cols, row_sum, p0=[ampx, centerx, wx,0])
        widthx = abs(poptx[2])
        center_x = poptx[1]
        
    except RuntimeError as e:
        print(e)
        
    try:
        popty, pcovy = curve_fit(Gaussian, rows, col_sum, p0=[ampy, centery, wy,-1e13])
        widthy = abs(popty[2])
        center_y = popty[1]  
        
    except RuntimeError as e:
        print(e)

    if do_plot:
        #see the input array
        plt.rcParams.update({'font.size' : 10})
        plt.figure(figsize=(12,5))
        plt.subplot(121)
        if vmax == None:
            vmax = array.max()
        
        plt.imshow(array, cmap = 'jet',vmin=0,vmax=vmax)
        
        if variablesToDisplay and logTime:
            variablesToDisplay = [ii.replace(' ','_') for ii in variablesToDisplay]
            plt.text(0,0,
                     variableLog.loc[logTime[count]][variablesToDisplay].to_string(name=showTimestamp).replace('Name','Time'), 
                     fontsize=7, ha='left', va='top',
                     bbox=dict(boxstyle="square", ec=(0,0,0), fc=(1,1,1), alpha=0.9))
        
        if column_density_xylim == None:
            column_density_xylim = np.zeros(4)
            # column_density_xylim[1] = len(array[0])
            # column_density_xylim[3] = len(array)
            column_density_xylim[1], column_density_xylim[3] = array.shape[1::-1]
            
        print("column_density_xylim = "+str(column_density_xylim))
        column_density_xylim = np.array(column_density_xylim)
        if column_density_xylim[1] == -1:
                column_density_xylim[1] = len(array[0])
        if column_density_xylim[3] == -1:
                column_density_xylim[3] = len(array) 
        plt.xlim(column_density_xylim[0], column_density_xylim[1])
        plt.ylim(column_density_xylim[3], column_density_xylim[2])
        plt.title(title)
        plt.colorbar(pad = .1)
        if save_column_density:
            plt.savefig(title + ".png", dpi = 600)
        #plot the sum over columns
        #plt.figure()
        plt.subplot(122)
        #plt.title("col sum (fit in x direction)")
        plt.plot(cols, row_sum, label="data_vs_x")
        
        plt.xlabel("pixel index")
        plt.ylabel("sum over array values")
        #plot the sum over rows
        #plt.figure()
        #plt.title("row sum (fit in y direction)")
        plt.plot(rows, col_sum, label="data vs y")
        
        plt.xlabel("pixel index")
        plt.ylabel("sum over array values")
        plt.tight_layout()
        plt.legend()
    
        plt.plot(cols, Gaussian(cols, *[ampx, centerx, wx,0]), label="guess vs x")
        plt.plot(rows, Gaussian(rows, *[ampy, centery, wy,0]), label="guess vs y")  
        plt.legend()
        
        if not np.isnan(widthx):
            plt.plot(cols, Gaussian(cols, *poptx), label="fit vs x")
            plt.legend()
            plt.tight_layout()
        if not np.isnan(widthy):
            plt.plot(rows, Gaussian(rows, *popty), label="fit vs y")  
            plt.legend()
            plt.tight_layout()

        plt.tight_layout()
        
    return widthx, center_x, widthy, center_y


def cd plotImgAndFitResult(imgs, *popts, bgs=[], filterLists=[],
                        fitFunc=MultiGaussian, axlist=['y', 'x'], dx=1,
                        plotRate=1, plotPWindow=5, figSizeRate=1, fontSizeRate=1, 
                        variableLog=None, variablesToDisplay=[], logTime=[], showTimestamp=False,
                        textLocationY=1, textVA='bottom', 
                        xlabel=['pixels', 'position ($\mu$m)', 'position ($\mu$m)'],
                        ylabel=['pixels', '1d density (atoms/$\mu$m)', ''],
                        title=[], 
                        rcParams={'font.size': 10, 'xtick.labelsize': 9, 'ytick.labelsize': 9}): 
    
    plt.rcParams.update(rcParams)
    plt.rcParams['image.cmap'] = 'jet'
    
    axDict = {'x': 0, 'y':1}

    N = len(popts)
    
    if filterLists:
        variableLog, items = DataFilter(variableLog, imgs, *popts, *bgs, filterLists=filterLists)
        imgs, popts, bgs = items[0], items[1: N+1], items[N+1:]

    imgNo = len(imgs)
    
    if plotRate < 1:
        mask = np.random.rand(imgNo) < plotRate
        imgs = imgs[mask]
        imgNo = mask.sum()
        
        popts = list(popts)
        for n in range(N):
            popts[n] = np.array(popts[n])[mask]
            if bgs and bgs[0] is not None:
                bgs[n] = np.array(bgs[n])[mask]            
    
    oneD_imgs = []
    xx = []
    xxfit = []
    if not title:
        title=['Column Density', '1D density vs ', '1D density vs ']
        
    if variablesToDisplay and not logTime is not None:
                logTime = variableLog.index
    
    for n in range(N):
        oneD = imgs.sum( axis=axDict[axlist[n]] + 1 ) * dx / 1e6**2
        L = len(oneD[0])
        oneD_imgs.append(oneD)
        xx.append(np.arange(0, L) * dx)
        xxfit.append(np.arange(0, L, 0.1) * dx)
        title[n+1] += axlist[n]
        
    for ind in range(imgNo):
        #Creat figures
        plotInd = ind % plotPWindow
        if plotInd == 0:
            plotNo = min(plotPWindow, imgNo-ind)
            fig, axes = plt.subplots(plotNo , N+1, figsize=(figSizeRate*3*(N+1), figSizeRate*1.5*plotNo), 
                                     squeeze = False, sharex='col', layout="constrained")
            for n in range(N+1):
                axes[-1, n].set_xlabel(xlabel[n])
                axes[int(plotNo/2), n].set_ylabel(ylabel[n])
                axes[0, n].set_title(title[n])
        
        #Plot the Images
        axes[plotInd, 0].imshow(imgs[ind], vmin=0)
        
        for n in range(N):
            axes[plotInd, n+1].plot(xx[n], oneD_imgs[n][ind], '.', markersize=3)
            if popts[n][ind] is not None:
                if bgs is not None and bgs[0] is not None:
                    axes[plotInd, n+1].plot(xx[n], fitFunc(xx[n], *popts[n][ind]) + bgs[ind])
                    axes[plotInd, n+1].plot(xx[n], bgs[ind], '.', markersize=0.3)
                else:
                    axes[plotInd, n+1].plot(xxfit[n], fitFunc(xxfit[n], *popts[n][ind]))
            
            
            axes[plotInd, n+1].ticklabel_format(axis='both', style='sci', scilimits=(-3,3))
            axes[plotInd, n+1].tick_params('y', direction='in', pad=-5)
            plt.setp(axes[plotInd, n+1].get_yticklabels(), ha='left')
            
        if variablesToDisplay:

            variablesToDisplay = [ii.replace(' ','_') for ii in variablesToDisplay]
            axes[plotInd,0].text(-0.05, textLocationY, 
                            variableLog.loc[logTime[ind]][variablesToDisplay].to_string(name=showTimestamp).replace('Name','Time'), 
                            fontsize=5*fontSizeRate, ha='left', va=textVA, transform=axes[plotInd,0].transAxes, 
                            bbox=dict(boxstyle="square", ec=(0,0,0), fc=(1,1,1), alpha=0.7))


def AnalyseFittingResults(popts, ax='Y', logTime=None, 
                          columns=['center', 'width', 'atomNumber']):
    results = []
    for p in popts:
        center, width, atomNumber = [np.nan] * 3
        
        if p is not None:
            N = len(p) // 3
            amp = p[0:N]
            center = p[N:2*N]
            width = p[2*N:3*N]
            atomNumber = (amp * width * (2*np.pi)**0.5).sum()
            if N == 1:
                center = center[0]
                width = width[0]                

        results.append([center, width, atomNumber])
    
    columns = [ax.upper() + ii for ii in columns]
    return pd.DataFrame(results, index=logTime, columns=columns).rename_axis('time')


def fit2Lines(x, ys, xMean, y1Mean, y2Mean, pointsForGuess=3):
    mergingPoint = ( np.array([ len(ii) for ii in ys ]) < 2 ).argmax()
    if mergingPoint > 0 and mergingPoint < pointsForGuess:
        pointsForGuess = mergingPoint
        
    # Initial guess
    x1 = xMean[:pointsForGuess]
    p1 = np.poly1d( np.polyfit(x1, y1Mean[:pointsForGuess], deg=1) )
    p2 = np.poly1d( np.polyfit(x1, y2Mean[:pointsForGuess], deg=1) )
    
    x1 = []
    y1 = []
    y2 = []
    for ii in range(len(x)):
        if len( ys[ii] ) < 2:
            continue
        
        xi = x[ii]
        yi1, yi2 = ys[ii]
        pi1, pi2 = p1(xi), p2(xi)
        
        d1 = max(abs(yi1-pi1), abs(yi2-pi2)) 
        d2 = max(abs(yi1-pi2), abs(yi2-pi1)) 
        
        if d2 < d1:
            yi1, yi2 = yi2, yi1
        
        x1.append(xi)
        y1.append(yi1)
        y2.append(yi2)
    
    
    p1 = np.poly1d( np.polyfit(x1, y1, deg=1) )
    p2 = np.poly1d( np.polyfit(x1, y2, deg=1) )
    
    if abs(p1[0]) > abs(p2[0]):
        p1, p2 = p2, p1
        y1, y2 = y2, y1
    return p1, p2, y1, y2

def odtMisalign(df,
                rcParams={'font.size': 10, 'xtick.labelsize': 9, 'ytick.labelsize': 9}): 
    plt.rcParams.update(rcParams)
    df = df.sort_values(by='ODT_Misalign')
    
    xx = df.center_Basler.values
    df = df.join([df.Ycenter.apply(min).rename('y1'), df.Ycenter.apply(max).rename('y2')])

    dfMean = df.groupby('ODT_Misalign').mean()
    dfStd = df.groupby('ODT_Misalign').std(ddof=0)

    xxMean = dfMean.center_Basler.values
    y1Mean = dfMean.y1.values
    y2Mean = dfMean.y2.values
    
    p1, p2, y1group, y2group = fit2Lines(xx, df.Ycenter.values, xxMean, y1Mean, y2Mean )
    root = np.roots(p1 - p2)[0]

    df = df.join( pd.DataFrame({'y1group': y1group, 'y2group': y2group} , index=df.index), rsuffix='r' )
    dfMean = df.groupby('ODT_Misalign').mean()
    dfStd = df.groupby('ODT_Misalign').std(ddof=0)

    xxfit = np.arange(xx.min(), xx.max())
    fig, ax = plt.subplots(1,1, figsize=(8,6), layout="constrained")
    N = 5
    ax.plot(xxfit, np.polyval(p1, xxfit), label='first pass')
    ax.plot(xxfit, np.polyval(p2, xxfit), label='second pass')
    ax.errorbar(dfMean.center_Basler, dfMean.y1group, N*dfStd.y1group, N*dfStd.center_Basler, ls='', color='r')
    ax.errorbar(dfMean.center_Basler, dfMean.y2group, N*dfStd.y2group, N*dfStd.center_Basler, ls='', color='r')
    ax.text(0.05,0.01, 'First pass y = {:.2f}\n'.format(np.mean(y1group))
            + 'Cross at   x = {:.2f}\n'.format(root)
            + 'std for x: {}\n'.format(np.round(dfStd.center_Basler.values, 2))
            + 'std for y: {}\n'.format(np.round(dfStd.y1group.values, 2))
            + '               {}\n'.format(np.round(dfStd.y2group.values, 2)), 
            va='bottom', transform=ax.transAxes, fontsize=8)
    ax.set_xlabel('Position On Basler Camera')
    ax.set_ylabel('Position On Zyla Camera')
    ax.legend()
    print('Coordinates for aligning:\n{:.3f}, {:.3f}'.format(np.mean(y1group), root))
    
def odtAlign(df, expYcenter, expCenterBasler, repetition=1, 
             rcParams={'font.size': 10, 'xtick.labelsize': 9, 'ytick.labelsize': 9}): 
    plt.rcParams.update(rcParams)
    df = df.reset_index()
    dfMean = df.groupby(df.index//repetition).mean()
    dfStd = df.groupby(df.index//repetition).std(ddof=0) 
    
    cols = ['Ycenter', 'YatomNumber', 'center_Basler', 'Ywidth']
    
    x = dfMean.index
    y = dfMean[cols]
    yErr = dfStd[cols]

    expected = [expYcenter, None, expCenterBasler, None]
    fig, axes = plt.subplots(2, 2, figsize=(10,6), sharex=True, layout="constrained")
        
    for ii, ax in enumerate(axes.flatten()):
        ax.errorbar(x, y[cols[ii]], yErr[cols[ii]])
        ax.set_ylabel(y[cols[ii]].name)
        if cols[ii] == 'YatomNumber':
            formatstr = '{:.2e}\n'
        else: 
            formatstr = '{:.2f}\n'
        ax.text(0.01,0.98, 'Latest value:    ' + formatstr.format(y[cols[ii]].iloc[-1]), 
                va='top', transform=ax.transAxes)
        ax.text(0.01,0.9, 'Average Value: ' + formatstr.format(y[cols[ii]].mean()),
                va='top', transform=ax.transAxes)        
        ax.ticklabel_format(axis='y', style='sci', scilimits=(-3,5))
        if expected[ii]:
            ax.axhline(y=expected[ii], ls='--', color='g')
            yrange = max(2*y[cols[ii]].std(ddof=0), 1.5 * np.abs(expected[ii] - y[cols[ii]].iloc[-1]))
            ax.set(ylim=[expected[ii]-yrange, expected[ii]+yrange])

   

def CalculateFromZyla(dayFolderPath, dataFolders, variableLog=None, 
                      repetition=1, examNum=None, examFrom=None, 
                      plotRate=0.2, plotPWindow=5, uniformscale=0, 
                      variablesToDisplay=[], variableFilterList=None, 
                      showTimestamp=False, pictureToHide=None,
                      subtract_bg=True, signal_feature='narrow', signal_width=10,
                      rowstart=30, rowend=-30, columnstart=30, columnend=-30,
                      angle_deg= 2, #rotates ccw
                      subtract_burntin=0, 
                      lengthFactor=1e-6
                      ):    
    
    dataFolderPaths = [ os.path.join(dayFolderPath, f) for f in dataFolders ]
    examFrom, examUntil = GetExamRange(examNum, examFrom, repetition)
    
    picturesPerIteration = 4 if subtract_burntin else 3    
    params = ExperimentParams(t_exp = 10e-6, picturesPerIteration= picturesPerIteration, cam_type = "zyla")
    images_array = None
    NoOfRuns = []
    
    for ff in dataFolderPaths:
        if images_array is None:
            images_array, fileTime = LoadSpooledSeries(params = params, data_folder = ff, 
                                                                       return_fileTime=1)
            NoOfRuns.append(len(fileTime))
        else:
            _images_array, _fileTime = LoadSpooledSeries(params = params, data_folder = ff, 
                                                                           return_fileTime=1)
            images_array = np.concatenate([images_array, _images_array], axis=0)
            fileTime = fileTime + _fileTime
            NoOfRuns.append(len(_fileTime))
    
    images_array = images_array[examFrom: examUntil]
    fileTime = fileTime[examFrom: examUntil]
    
    dataFolderindex = []
    [ dataFolderindex.extend([dataFolders[ii].replace(' ','_')] * NoOfRuns[ii]) for ii in range(len(NoOfRuns)) ]
    dataFolderindex = dataFolderindex[examFrom: examUntil]
    
    logTime = Filetime2Logtime(fileTime, variableLog)
        
    if variableFilterList and variableLog is not None:    
        filteredList = VariableFilter(logTime, variableLog, variableFilterList)
        images_array = np.delete(images_array, filteredList, 0)
        dataFolderindex = np.delete(dataFolderindex, filteredList, 0)
        logTime = np.delete(logTime, filteredList, 0)
            
    if pictureToHide:
        images_array = np.delete(images_array, pictureToHide, 0)
        dataFolderindex = np.delete(dataFolderindex, pictureToHide, 0)
        if logTime:
            logTime = np.delete(logTime, pictureToHide, 0)
    
    # ImageAnalysisCode.ShowImagesTranspose(images_array)
    Number_of_atoms, N_abs, ratio_array, columnDensities, deltaX, deltaY = absImagingSimple(images_array, 
                    firstFrame=0, correctionFactorInput=1.0,  
                    subtract_burntin=subtract_burntin, preventNAN_and_INF=True)
    
    imgNo = len(columnDensities)
    print('{} images loaded.'.format(imgNo))
        
    results = []
    
    #Generate the list for plot based on the total image # and the set ploting ratio
    plotList = np.arange(imgNo)[np.random.rand(imgNo) < plotRate]
    plotNo = len(plotList)
    plotInd = 0
    
    axs = [None] 
    axRowInd = 0
    axRowNo = None
    
    if uniformscale:
        vmax = columnDensities.max()
        vmin = columnDensities.min()
    else:
        vmax = None
        vmin = 0
   
    for ind in range(imgNo):
        
        # do_plot = 1 if ind in plotList else 0
        
        if ind in plotList:
            do_plot = 1
        else: do_plot = 0
        
        if do_plot:
            axRowInd = plotInd % plotPWindow #The index of axes in one figure
            if axRowInd == 0:
                # if ind//plotPWindow>0:
                #     fig.tight_layout()
                axRowNo = min(plotPWindow, plotNo-plotInd) #The number of rows of axes in one figure
                fig, axs = plt.subplots(axRowNo , 3, figsize=(3*3, 1.8*axRowNo), squeeze = False, layout="constrained")
                # plt.subplots_adjust(hspace=0.14, wspace=0.12)
            plotInd += 1
            
        rotated_ = rotate(columnDensities[ind], angle_deg, reshape = False)[rowstart:rowend,columnstart:columnend]
        # rotated_=columnDensities[ind]
        if ind==0: #first time
            rotated_columnDensities =np.zeros((imgNo, *np.shape(rotated_)))
        rotated_columnDensities[ind] = rotated_
    
        #preview:
        dx=params.camera.pixelsize_meters/params.magnification
        
        popt0, popt1 = fitgaussian2D(rotated_columnDensities[ind], dx=dx, 
                                                      do_plot = do_plot, ax=axs[axRowInd], Ind=axRowInd, imgNo=axRowNo,
                                                      subtract_bg = subtract_bg, signal_feature = signal_feature, signal_width=signal_width,
                                                      vmax = vmax, vmin = vmin,
                                                      title="1D density", title2D="column density",
                                                      xlabel1D="position ($\mu$m)", ylabel1D="1d density (atoms/$\mu$m)",                                                  
                                                      xscale_factor=1/lengthFactor, yscale_factor=lengthFactor)
        
        if do_plot and variableLog is not None:
            variablesToDisplay = [ii.replace(' ','_') for ii in variablesToDisplay]
            axs[axRowInd,0].text(0,1,
                                 'imgIdx = {}'.format(ind) + '\n'
                            + variableLog.loc[logTime[ind]][variablesToDisplay].to_string(name=showTimestamp).replace('Name','Time'), 
                            fontsize=5, ha='left', va='top', transform=axs[axRowInd,0].transAxes, 
                            bbox=dict(boxstyle="square", ec=(0,0,0), fc=(1,1,1), alpha=0.7))
                
        if popt0 is None:
            center_x, width_x, atomNumberX = [np.nan] * 3
        else:            
            amp_x, center_x, width_x, _ = popt0
            atomNumberX = amp_x * width_x * (2*np.pi)**0.5            
        if popt1 is None:
            center_y, width_y, atomNumberY = [np.nan] * 3
        else:                    
            amp_y, center_y, width_y, _ = popt1
            atomNumberY = amp_y * width_y * (2*np.pi)**0.5
        
        convert = 1e6
        results.append([center_y*convert, width_y*convert, atomNumberY, 
                        center_x*convert, width_x*convert, atomNumberX])
            
    df = pd.DataFrame(results, index=logTime,
                      columns=['Ycenter', 'Ywidth', 'AtomNumber', 'Xcenter', 'Xwidth', 'AtomNumberX'
                               ]
                      ).rename_axis('time')
    df.insert(0, 'Folder', dataFolderindex)
    
    if variableLog is not None:
        # variableLog = variableLog.loc[logTime]
        df = df.join(variableLog)
    
    return df


def DataFilter(info, *otheritems, filterLists=[]):   
    '''
    
    Parameters
    ----------
    info : TYPE
        DESCRIPTION.
    *filterLists : list of strings
        Lists of the filter conditions. Each condition should be in the form of 
        'ColumName+operator+value'. No spaces around the operator. Condtions
        will be conbined by logic or, and filters in different lists will be 
        conbined by logic and. 
    imgs : TYPE, optional
        DESCRIPTION. The default is None.

    Returns
    -------
    TYPE
        DESCRIPTION.

    '''
    if len(filterLists) == 0:
        return info, otheritems
    
    masks = []
    for fltlist in filterLists:
        maskSingleList = []
        for flt in fltlist:
            maskSingleList.append(eval( 'info.' + flt.replace(' ', '_') ))   
           
        if len(fltlist) > 1:
            for mask in maskSingleList[1:]:
                maskSingleList[0] &= mask
        masks.append(maskSingleList[0])
        
    if len(filterLists) > 1:
        for mask in masks[1:]:
            masks[0] |= mask
    
    if otheritems:
        otheritems = list(otheritems)
        for ii in range(len(otheritems)):
            otheritems[ii] = np.array(otheritems[ii])[mask[0]]
            
    else:
        return info[ masks[0] ], otheritems


def FilterByOr(df, filterLists):
    
    masks = []
    for flts in filterLists:
        masklist = []
        for flt in flts:
            masklist.append(eval( 'df.' + flt.replace(' ', '_') ))   
           
        if len(masklist) > 1:
            for mask in masklist[1:]:
                masklist[0] |= mask
        masks.append(masklist[0])
        
    if len(masks) > 1:
        for mask in masks[1:]:
            mask[0] &= mask
    return df[ mask[0] ]



def PlotFromDataCSV(df, xVariable, yVariable, filterLists=[],
                    groupby=None, groupbyX=0, iterateVariable=None,
                    figSize=1, legend=1, legendLoc=0,
                    threeD=0, viewElev=30, viewAzim=-45):
    '''
    

    Parameters
    ----------
    df : DataFrame
        Pandas dataframe from CalculateFromZyla or loaded from a saved data file.
    xVariable : str
        The name of the variable to be plotted as the x axis. It should be the 
        name of a column of the dataframe.
    yVariable : str
        The name of the variable to be plotted as the y axis. It should be the 
        name of a column of the dataframe.
    groupby : str, default: None
        The name of a dataframe column. If it is assigned, the data points will be
        averaged based on the values of this column, and the plot will be an
        errorbar plot.
    groupbyX : boolean, default: 0
        The name of a dataframe column. If it is true, the data points will be
        averaged based for each x value, and the plot will be an errorbar plot.
    iterateVariable : str, default: None
        The name of a dataframe column. If it is assigned, the plot will be divided
        into different groups based on the values of this column.        
    filterByAnd : list of strings, default: []
        A list of the filter conditions. Each condition should be in the form of 
        'ColumName+operator+value'. No spaces around the operator. Different condtions
        will be conbined by logic and. 
    filterByOr : list of strings, default: []
        A list of the filter conditions. Each condition should be in the form of 
        'ColumName+operator+value'. No spaces around the operator. Different condtions
        will be conbined by logic or. 
    filterByOr2 : list of strings, default: []
        The same as filterByOr, but a logical and will be performed for the 
        results of filterByOr2 and filterByOr.    
    threeD : boolean, default: 0
        Plot a 3-D line plot if set to True. 
    viewElev : float, default: 30
        The elevation angle of the 3-D plot. 
    viewAzim : float, default: -45
        The azimuthal angle of the 3-D plot. 

    Raises
    ------
    FileNotFoundError
        DESCRIPTION.

    Returns
    -------
    fig, ax.

    '''
    
        
    # if not os.path.exists(filePath):
    #     raise FileNotFoundError("The file does not exist!")
    
    # df = pd.read_csv(filePath)
    df = df[ ~np.isnan(df[yVariable]) ]
    df, _ = DataFilter(df, filterLists)
    
    columnlist = [xVariable, yVariable]
    
    if iterateVariable:
        iterateVariable.replace(' ', '_')
        iterable = df[iterateVariable].unique()
        iterable.sort()
        columnlist.append(iterateVariable)
    else:
        iterable = [None]
        threeD = 0
    
    if groupby == xVariable or groupbyX:
        groupbyX = 1  
        groupby = xVariable
    if groupby and not groupbyX:
        groupby.replace(' ', '_')
        columnlist.append(groupby)
    
    if threeD:
        fig, ax = plt.subplots(figsize=(9*figSize, 9*figSize), subplot_kw=dict(projection='3d'))
        ax.view_init(elev=viewElev, azim=viewAzim)
    else:
        fig, ax = plt.subplots(figsize=(10*figSize, 8*figSize))
    
    for ii in iterable:
        if ii is None:
            dfii = df[columnlist]
        else:
            dfii = df[columnlist][ (df[iterateVariable]==ii) ]
            
        if groupby:
            dfiimean = dfii.groupby(groupby).mean()
            dfiistd = dfii.groupby(groupby).std(ddof=0)
            
            yMean = dfiimean[yVariable]
            yStd = dfiistd[yVariable]
            
            if groupbyX:
                xMean = dfiimean.index
                xStd = None
            else:
                xMean = dfiimean[xVariable]
                xStd = dfiistd[xVariable]
            
            if threeD:
                ax.plot3D( [ii]*len(xMean), xMean, yMean,
                         label = '{} = {}'.format(iterateVariable, ii))                
            else:
                ax.errorbar(xMean, yMean, yStd, xStd, capsize=3,
                            label = '{} = {}'.format(iterateVariable, ii)) 
                #plt.scatter(xMean, yMean, s=8)
        else:
            ax.plot( dfii[xVariable], dfii[yVariable], '.', 
                     label = '{} = {}'.format(iterateVariable, ii))
            
    if threeD:
        ax.set(xlabel=iterateVariable, ylabel=xVariable, zlabel=yVariable)
        ax.ticklabel_format(axis='z', style='sci', scilimits=(-3,3))
    else:
        ax.set(xlabel=xVariable, ylabel=yVariable)
        ax.ticklabel_format(axis='y', style='sci', scilimits=(-3,3))
    fig.tight_layout()
    if iterateVariable and legend:
        plt.legend(loc=legendLoc)
    plt.show()
    
    return fig, ax
    

def temperature_model(t, w0, T):
    #I define the constants explicitly since this function is passed to curve fit
    kB = 1.38e-23 #Boltzmann's constant
    m = 9.988341e-27 #Li-6 mass in kg    
    t0 = 0
    model = w0*np.sqrt(   1 +       (kB/m)*abs(T)*(t-t0)**2/(w0**2)   )
    # model = w0*np.sqrt((kb*T*(t-t0)**2)/(m*w0**2))
    return model

def temperature_fit(params, widths_array, tof_array,label="",do_plot=False):
    #Inputs: params object, widths in meters, times in seconds
    #Optional: label like "x" or "y"
    
    min_time = min(tof_array)
    max_time = max(tof_array)
    min_width = min(widths_array)
    max_width = max(widths_array)
    
    #remove Nans and Infs
    good_indexes = np.isfinite(widths_array)
    tof_array = tof_array[good_indexes]
    widths_array = widths_array[good_indexes]
    
    w0guess = min_width
    slope = (max_width-min_width)/(max_time-min_time)
    Tguess = (slope)**2*params.m/params.kB 
    popt, pcov = curve_fit(temperature_model, tof_array, widths_array, p0 = [w0guess, Tguess])
    times_fit = np.linspace(min_time, max_time, 100)
    widths_fit = temperature_model(times_fit, popt[0], popt[1])
    
    if (do_plot):
        #plot the widths vs. position
        plt.figure(figsize=(3,2))
        plt.title("{} T = {:.2f} uK".format(label, popt[1]*1e6))
        plt.xlabel("Time of flight (ms)")
        plt.ylabel("width of atom cloud (um)")
        plt.scatter(1e3*tof_array, 1e6*widths_array)
        plt.plot(1e3*times_fit, 1e6*widths_fit)
        plt.tight_layout()
        # if data_folder:
        #     plt.savefig(data_folder+r'\\'+"temperature x.png", dpi = 500)
    
    return tof_array, times_fit, widths_fit, popt, pcov

 
def thermometry(params, images, tof_array, do_plot = False, data_folder = None):
    widthsx = np.zeros(len(images))
    widthsy = np.zeros(len(images))
    #fill arrays for widths in x and y directions
    for index, image in enumerate(images):
        widthsx[index], x, widthsy[index], y  = fitgaussian(image)
        widthsx[index] = widthsx[index]*params.camera.pixelsize_meters/params.magnification
        widthsy[index] = widthsy[index]*params.camera.pixelsize_meters/params.magnification
        if index == 0:
            print("widthx = "+str(widthsx[index]*1e6)+" um")
            print("widthy = "+str(widthsy[index]*1e6)+" um")
    #these plots will still show even if the fit fails, but the plot underneath the fit will not     
    # if (do_plot):
    #     plt.figure()
    #     plt.xlabel("Time of flight (ms)")
    #     plt.ylabel("1/e^2 width x of atom cloud (uncalibrated units)")
    #     plt.scatter(tof_array, widthsx)
        
    #     plt.figure()
    #     plt.xlabel("Time of flight (ms)")
    #     plt.ylabel("1/e^2 width y of atom cloud (uncalibrated units)")
    #     plt.scatter(tof_array, widthsy)        
        
    fitx_array, plotx_array, fitx, poptx, pcovx = temperature_fit(params, widthsx, tof_array)
    fity_array, ploty_array, fity, popty, pcovy = temperature_fit(params, widthsy, tof_array)
    if (do_plot):
        #plot the widths vs. position along x direction
        plt.figure()
        plt.title("Temperature fit x, T = {} uK".format(poptx[1]*1e6))
        plt.xlabel("Time of flight (ms)")
        plt.ylabel("width of atom cloud (um)")
        plt.scatter(1e3*tof_array, 1e6*widthsx)
        plt.plot(1e3*plotx_array, 1e6*temperature_model(plotx_array, *poptx))   
        if data_folder:
            plt.savefig(data_folder+r'\\'+"temperature x.png", dpi = 500)
        #plot the widths vs. position along y direction
        plt.figure()
        plt.title("Temperature Fit y, T = {} $\mu$K".format(popty[1]*1e6))
        plt.xlabel("Time of Flight (ms)")
        plt.ylabel("Width of Atom Cloud ($\mu$m)")
        plt.scatter(1e3*tof_array, 1e6*widthsy)
        plt.plot(1e3*ploty_array, 1e6*temperature_model(ploty_array, *popty)) 
        if data_folder:
            plt.savefig(data_folder+r'\\'+"temperature y.png", dpi = 500)        
    return poptx, pcovx, popty, pcovy
   
def thermometry1D(params, columnDensities, tof_array, thermometry_axis="x", 
                  do_plot = False, save_folder = None, reject_negative_width=False,
                  newfig=True):
    #1. Find cloud size (std dev) vs time
    widths=[]
    times=[]
    numbers=[]
    dx = params.camera.pixelsize_meters/params.magnification
    for index, density2D in enumerate(columnDensities):
        density1D = integrate1D(density2D, dx=dx, free_axis=thermometry_axis)
        xdata = np.arange(np.shape(density1D)[0])*dx
        popt_gauss  = fitgaussian1D(density1D,xdata,dx=dx, doplot=True, xlabel=thermometry_axis, ylabel="density")
        if popt_gauss is not None: #fit succeeded
            if popt_gauss[2] >0 or not reject_negative_width:
                w = abs(popt_gauss[2])
                widths.append(w)
                times.append(tof_array[index])
                numbers.append(popt_gauss[0]* w*(2*np.pi)**0.5 ) #amp  = N/(w*(2*np.pi)**0.5)
    numbers=np.array(numbers)
    widths=np.array(widths)
    times=np.array(times)       
    #2. Fit to a model to find temperature    
    # fitx_array, plotx_array, fit, popt, pcov = temperature_fit(params, widths, times)
    try:
        tof_array, times_fit, widths_fit, popt, pcov = temperature_fit(params, widths, times)
    except RuntimeError:
        popt = None
        pcov = None
        
    if (do_plot):
        #plot the widths vs. time
        if newfig:
            plt.figure()
        plt.rcParams.update({'font.size': 14})
        AxesAndTitleFont = 20
        if popt is not None:
            plt.title("{0}: T = {1:.2f} $\mu$K".format(thermometry_axis, popt[1]*1e6), fontsize = AxesAndTitleFont)
            plt.plot(1e3*times_fit, 1e6*widths_fit, color = 'blue', zorder =1)
        plt.xlabel("Time of Flight (ms)", fontsize = AxesAndTitleFont)
        plt.ylabel("Std. dev ($\mu$m)", fontsize = AxesAndTitleFont)
        plt.scatter(tof_array/1e-3, widths/1e-6, color = 'red', zorder = 2)
        
        
        plt.tight_layout()
        if save_folder:
            plt.savefig(save_folder+r'\\'+"temperature {}.png".format(thermometry_axis), dpi = 300)
        # plt.figure()
        # plt.plot(1e3*tof_array, numbers,'o')
        # plt.xlabel("Time of flight (ms)")
        # plt.ylabel("Atom number")
        # plt.title("Atom Number {}".format(thermometry_axis))
        plt.tight_layout()
        if save_folder:
            plt.savefig(save_folder+r'\\'+"atom number {}.png".format(thermometry_axis), dpi = 300)
    return popt, pcov
   
    


   
def exponential(x, a, tau, c):
    return a * np.exp(-x/tau) + c    

def fit_exponential(xdata, ydata ,dx=1, doplot = False, label="", title="", 
                    newfig=True, xlabel="",ylabel="", offset = None, legend=False):
    

    #fit for the parameters a , b, c
    a = max(ydata) - min(ydata)
    tau = (max(xdata)-min(xdata))/2
    c = min(ydata)
    xfit = np.linspace(min(xdata),max(xdata), 1000)
    
    if offset is None:
        func = exponential
        guess= [a,tau,c]
        label = 'fit: a=%5.3f, tau=%5.3f, c=%5.3f'
    else:
        func = lambda x,a,tau: exponential(x,a,tau,offset)
        guess = [a,tau]
        label = 'fit: a=%5.2e\n tau=%5.2e\n c={:.2e} (Fixed)'.format(offset)
        
    popt, pcov = curve_fit(func, xdata, ydata, p0=guess)       

    #poptarray([2.56274217, 1.37268521, 0.47427475])
    plt.plot(xdata, ydata,'o')
    plt.plot(xfit, func(xfit, *popt), 'r-', label= label % tuple(popt))

    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    if legend:
        plt.legend()
    plt.tight_layout()
    plt.show()
    return popt, pcov
    
    
def twobodyloss(t, k, c):
    return (k*t+c)**-1    

def fit_2bodyloss(xdata, ydata ,dx=1, doplot = False, label="", title="", 
                    newfig=True, xlabel="",ylabel="", offset = None):
    

    #fit for the parameters a , b, c
    k = 2 / (max(xdata)-min(xdata))
    c = max(ydata)
    xfit = np.linspace(min(xdata),max(xdata), 1000)
    
    if offset is None:
        func = twobodyloss
        guess= [k,c]
        label = 'fit: k=%5.3f, c=%5.3f'
    else:
        func = lambda t,k,c: twobodyloss(t,k,offset)
        guess = [k,c]
        label = 'fit: k=%5.3f, c={:.3f} (Fixed)'.format(offset)
        
    popt, pcov = curve_fit(func, xdata, ydata, p0=guess)       
    
    #poptarray([2.56274217, 1.37268521, 0.47427475])
    plt.plot(xfit, func(xfit, *popt), 'r-', label= label % tuple(popt))

    plt.xlabel('Time (seconds)')
    plt.ylabel('Number of atoms')
    plt.legend()
    plt.show()    
    



def CircularMask(array, centerx = None, centery = None, radius = None):
    rows, cols = array.shape[-2:]
    
    if centerx == None:
        centerx = int(cols/2)
    if centery == None:
        centery = int(rows/2)
    if radius == None:
        radius = min(centerx, centery, cols-centerx, rows-centery)
    y, x = np.ogrid[-centery:rows-centery, -centerx:cols-centerx]
    mask = x*x + y*y <= radius*radius
    
    arraycopy = array.copy()
    arraycopy[..., ~mask] = 0
    
    return arraycopy, arraycopy.max()



    

'''

#Gaussian_fit takes an array of the summed atom numbers. It outputs a gaussian width, a full fit report, and an x axis array
def Gaussian_fit(images, params, slice_array, tof, units_of_tof, dataFolder='.'):
    xposition = params.andor_pixel_size*np.linspace(0, len(slice_array),len(slice_array))
    aguess = np.max(slice_array)
    muguess = params.andor_pixel_size*np.where(slice_array == np.max(slice_array))[0][0]
    w0guess = params.andor_pixel_size*len(slice_array)/4 #the standard dev. of the Gaussian
    cguess = np.min(slice_array)
    paramstemp = Parameters()
    paramstemp.add_many(
        ('a', aguess,True, None, None, None),
        ('mu', muguess, True, None, None, None),
        ('w0', w0guess, True, None, None, None),
        ('c', cguess, True, None, None, None),
        )
        
    model = lmfit.Model(Gaussian)
    result = model.fit(slice_array, x=xposition, params = paramstemp)
    gwidth = abs(result.params['w0'].value)
    return  gwidth, result, xposition


#Here I call the Gaussian_fit function on all of the expanding cloud pictures to output widths for all of them.
    half_of_pictures = int(params.number_of_pics/2)
    gaussian_widths_x = np.zeros(half_of_pictures)
    gaussian_widths_y = np.zeros(half_of_pictures)
    num_atoms_vs_x, num_atoms_vs_y, atoms_max = temp(slice_array)
 
    for i in range(half_of_pictures):
        fittemp_x = Gaussian_fit(num_atoms_vs_x[2*i+1,:])
        fittemp_y = Gaussian_fit(num_atoms_vs_y[2*i+1,:])
        gaussian_widths_x[i] = fittemp_x[0]
        gaussian_widths_y[i] = fittemp_y[0]
        
        
        if params.ready_to_save == 'true':
        
            #save Gaussian fit in x direction plot
            fit0_x = Gaussian_fit(num_atoms_vs_x[2*i+1,:])
            plt.figure()
            plt.rcParams.update({'font.size':9})
            plt.title('TOF = {}'.format(tof[i])+units_of_tof+' horizontal plot, standard dev. = {}m'.format(round(abs(fit0_x[0]), 5)))
            plt.xlabel("Position (m)")
            plt.ylabel("Number of atoms in MOT")
            plt.plot(fit0_x[2], num_atoms_vs_x[2*i+1,:], 'g.', label='Signal')
            plt.plot(fit0_x[2], fit0_x[1].best_fit, 'b', label='Fit')
            plt.legend()
            plt.tight_layout()
            plt.savefig(dataFolder +r'\TOF = {}'.format(tof[i])+units_of_tof+' horizontal plot.png', dpi = 300)
            plt.close()  
            
            #save Gaussian fit in y direction plot
            fit0_y = Gaussian_fit(num_atoms_vs_y[2*i+1,:])
            plt.figure()
            plt.title('TOF = {}'.format(tof[i])+units_of_tof+' vertical plot, standard dev. = {}m'.format(round(abs(fit0_y[0]), 5)))
            plt.xlabel("Position (m)")
            plt.ylabel("Number of atoms in MOT")
            plt.plot(fit0_y[2], num_atoms_vs_y[2*i+1,:], 'g.', label='Signal')
            plt.plot(fit0_y[2], fit0_y[1].best_fit, 'b', label='Fit')
            plt.legend()
            plt.tight_layout()
            plt.savefig(dataFolder+r'\TOF = {}'.format(tof[i])+units_of_tof+' vertical plot.png', dpi = 300)
            plt.close()
           
            #save the picture from Andor
            plt.figure()
            plt.title("Signal inside red rectangle")
            plt.imshow(images[2*i+1,params.ymin:params.ymax,params.xmin:params.xmax],cmap="gray", origin="lower",interpolation="nearest",vmin=np.min(images),vmax=np.max(images))
            plt.savefig(dataFolder+r'\TOF = {}'.format(tof[i])+units_of_tof+' signal inside red rectangle.png', dpi = 300)
            plt.close()
            

    gaussian_widths_x = np.flip(gaussian_widths_x)
    gaussian_widths_y = np.flip(gaussian_widths_y)


#Here we import the relevant TOF file and combine it with the gaussian widths
    widths_tof_x = np.zeros((len(gaussian_widths_x),2))
    widths_tof_y = np.zeros((len(gaussian_widths_y),2))

    for i in range(len(gaussian_widths_x)):
         widths_tof_x[i] = (gaussian_widths_x[i], tof[i])
         widths_tof_y[i] = (gaussian_widths_y[i], tof[i])

# save the data in a csv file
    if params.ready_to_save =='true':
        csvfilename_x = dataFolder+r"\widths_vs_tof_x.csv"
        csvfilename_y = dataFolder+r"\widths_vs_tof_y.csv"
        np.savetxt(csvfilename_x, widths_tof_x, delimiter = ",") 
        np.savetxt(csvfilename_y, widths_tof_y, delimiter = ",") 


def find_nearest(array, value):
    array = np.asarray(array)
    idx = (np.abs(array - value)).argmin()
    return array[idx]

def exponential(x, m, t, b):
    return m * np.exp(-t * x) + b
    
'''







# def fit_decay():
    
    #fit parameters
    # value = atom_max*np.exp(-1)
    # emin1 = find_nearest(array, value)
    # finder = np.where(N_atoms == emin1)
#     array_number = int(finder[0])
#     #print("array_number: ", array_number)
#     #######################################This is the time for the function to reach e**-1 of max value
#     emin1_time = Picture_Time[array_number]
#     atom_fraction = N_atoms/max(N_atoms)
    
    
    
#     p0 = (count_spooled.atom_max, 1/emin1_time, 0) # start with values near those we expect
#     params, cv = scipy.optimize.curve_fit(exp, Picture_Time, N_atoms, p0)
#     m, t, b = params
    
#     #Quality of fit
#     squaredDiffs = np.square(N_atoms - exp(Picture_Time, m, t, b))
#     squaredDiffsFromMean = np.square(N_atoms - np.mean(N_atoms))
#     rSquared = 1 - np.sum(squaredDiffs) / np.sum(squaredDiffsFromMean)
#     print(f"R² = {rSquared}")
#     print(f"Y = {m} * e^(-{t} * x) + {b}")
        
#     # plot the results
#     plt.plot(Picture_Time, N_atoms, '.', label="data")
#     plt.plot(Picture_Time, exp(Picture_Time, m, t, b), '--', label="fitted")
#     plt.title("Fitted Exponential Curve", fontsize = 18)
#     if m < 10**5:
#         pressure = t/(6.4*10**7)
#         print("It appears that this decay occurs in the low density limit.")
#         print("Based off of this assumption, the background pressure of the vacuum chamber appears to be {pressure} torr.")
    
    
# def fit_load():
#     p0 = (atom_max, (1-math.log(math.e-1))/emin1_time, atom_max) # start with values near those we expect
#     params, cv = scipy.optimize.curve_fit(exp, Picture_Time, N_atoms, p0)
#     m, t, b = params
    
#     #Quality of fit
#     squaredDiffs = np.square(N_atoms - exponential(Picture_Time, m, t, b))
#     squaredDiffsFromMean = np.square(N_atoms - np.mean(N_atoms))
#     rSquared = 1 - np.sum(squaredDiffs) / np.sum(squaredDiffsFromMean)
#     print(f"R² = {rSquared}")
#     print(f"Y = {m} * e^(-{t} * x) + {b}")
#     # plot the results
#     plt.plot(Picture_Time, N_atoms-min(N_atoms), '.', label="data")
#     plt.plot(Picture_Time, Load_Decay(Picture_Time, m, t, b)-min(N_atoms), '--', label="fitted")
#     plt.title("Atoms Loaded Over Time", fontsize = 20)    

def imageFreqOptimization(imgfreqs, atomNumbers,ratio_array):
    plt.figure(figsize=(5,4))
    plt.plot(imgfreqs,atomNumbers,'o')
    plt.xlabel("Freq (MHz)")
    plt.ylabel("Apparent atom number")
    plt.tight_layout()
    plt.show()
    
    imax = np.max(ratio_array)
    imin = np.min(ratio_array)
    number_of_iterations = np.shape(atomNumbers)[0]
    fig, axes = plt.subplots(1,number_of_iterations, sharex='all', sharey='all')
    for it in range(number_of_iterations):
        # ax = plt.subplots(1,params.number_of_iterations,it+1, sharex='all', sharey='all')
        axes[it].imshow(ratio_array[it,:,:],cmap="gray", vmin=imin, vmax=imax)
        # ax.set_size_inches(18.5, 10.5)
    #plt.tight_layout()
    plt.subplots_adjust(wspace=None, hspace=None)
    plt.tight_layout()
    plt.show()

#if __name__ == "__main__":
    #TESTING Script:
    # data_folder =  'odt test tof 4ms'   
    # rowstart = 0#450
    # rowend = -1#560
    # columnstart = 0#600
    # columnend =-1 #900
    # config = LoadConfigFile(data_folder)
    # params = ExperimentParams(config, picturesPerIteration=3)        
    # abs_img_data = LoadSpooledSeries(params, data_folder=data_folder, background_file_name="")
    # Number_of_atoms, N_abs, ratio_array, n2d = absImagingSimple(abs_img_data, firstFrame=0, correctionFactorInput=1, rowstart = rowstart, rowend=rowend,columnstart=columnstart,columnend=columnend)
    # print(np.shape(ratio_array[0]))
    
    # # imageFreqOptimization(np.loadtxt(data_folder+"/imgfreq.txt"), Number_of_atoms, ratio_array, params)
    # plt.imshow(ratio_array[0][rowstart:rowend,columnstart:columnend],vmin=0,vmax=1.2,cmap="gray")
    # densityvsrow = np.sum(n2d[0][rowstart:rowend,columnstart:columnend], 1)
    # print("densityvsrow = "+str(np.shape(densityvsrow)))
    # plt.figure()
    # plt.plot(densityvsrow)
    # #plt.imshow(n2d[0],vmin=0,cmap="gray")
    # plt.show()
    
    
    
    
    
    # for r in range(rows):
    #     for c in range(cols):
    #         if not np.isfinite(ratio[r][c]):
    #             print("FOUND NAN/inf")
    #             ratio[r][c]= 1
    #             print(ratio[r][c])
    #plt.imshow(ratio_array[7],vmin=0,vmax=1.5,cmap="gray")
    #plt.show()
    # CountsToAtoms(params, images[3,4,:,:])

    # images = loadSeriesPGM(params, root_filename="cMOTtest", number_of_pics=1, picturesPerIteration=1, n_params=0, data_folder= ".", background_file_name="")       
    # ShowImagesTranspose(images)    

    #raw_img = loadRAW("test3.raw")
    
    # print("Number of iterations=",params.number_of_iterations)
    
    # N_array = np.zeros(6) 
    # for x in range(6):
    #     abs_img_data = LoadSpooledSeries(params, data_folder=str(x+1), background_file_name="")
    #     Number_of_atoms, N_abs = absImagingSimple(abs_img_data)
    #     N_array[x] = N_abs
    # print(N_array)
    # N_list = N_array.tolist()
    # print(type(N_list))
    # freqs = [230, 231, 232, 233.5, 236.5, 235.8]
    # plt.figure
    # plt.plot(freqs, N_list)
    # plt.show()
        # abs_img_test = LoadSpooledSeries(params, data_folder=str(x+1), background_file_name="")
        # print(np.shape(abs_img_test))
        # #ShowImagesTranspose(abs_img_test, False)
        # subtracted1 = abs_img_test[0,0,:,:] - abs_img_test[0,2,:,:]
        # subtracted2 = abs_img_test[0,1,:,:] - abs_img_test[0,2,:,:]
        # ratio = subtracted1 / subtracted2
        
        # correctionFactor = np.mean(ratio[-5:][:])
        # print("correction factor=",correctionFactor)
        # ratio /= correctionFactor
        # OD = -1 * np.log(ratio)
        # N_abs = np.sum(OD) 
        # N_array[x] = N_abs
        # magnification = 0.6 #75/125 (ideally)
        # detuning = 2*np.pi*0 #how far from max absorption @231MHz. if the imaging beam is 230mhz then delta is -1MHz. unit is Hz
        # gamma = 36.898e6 #units Hz
        # wavevector =2*np.pi/(671e-9) #units 1/m
        # sigma = (6*np.pi / (wavevector**2)) * (1+(2*detuning/gamma)**2)**-1 
        # n2d = OD /sigma 
        # deltaX = 6.5e-6/magnification #pixel size in atom plane
        # deltaY = deltaX
        # N_atoms = np.sum(n2d) * deltaX * deltaY
        # print("number of atoms: ", N_atoms/1e6,"x10^6")        
    

    # plt.figure()
    # plt.imshow(OD)
    # plt.show()
    
    
    # count_x = np.sum(ratio,axis = 0) #sum over y direction/columns 
    # count_y = np.sum(subtracted1,axis = 1)
    
    # plt.figure()
    # plt.plot(OD[100,:])
    # plt.show()
    
    # plt.figure()
    # plt.imshow(ratio,cmap="gray")
    # plt.show()
    
    
    # #atomsPerPixel = CountsToAtoms(params, counts)
    
    # #ShowImagesTranspose(atomsPerPixel)
    
    # print(np.shape(images1))
    # print(np.shape(signal1))
    

    
    
    #atomNumbers = ImageTotals(atomsPerPixel)
    
    #print(atomNumbers)
    
    #number_of_pics = int(config['Acquisition']['NumberinKineticSeries'])
    #print(number_of_pics)
    
    # images = LoadSpooledSeries(config, data_folder= "." , background_file_name= "spool_background.dat", picturesPerIteration=3)
    # #images = LoadNonSpooledSeries(...)
    
    # atoms_per_pixel_images = GetCountsFromRawData(images,config)
    
    # #analyse it somehow:
    # #Find the total number of atoms at the end of each iteration
    # atom_numbers = GetTotalNumberofAtoms(atoms_per_pixel_images)
    
    # print("Number of atoms in 2nd picture of iteration 0:",atom_numbers[0][1])
    
    # #Do a fit:
    # result = DoExponentialFit(atom_numbers[:][1])
    
    # print(np.shape(images))
    
    
    
    

#     #here I am making a plot of the first gaussian with the fit for reference
#     fit0_x = Gaussian_fit(num_atoms_vs_x[PreviewIndex,:])
#     plt.figure()
#     plt.rcParams.update({'font.size':9})
#     plt.title('Atoms TOF horizontal example plot, standard dev. = {}m'.format(round(fit0_x[0], 5)))
#     plt.xlabel("Position (m)")
#     plt.ylabel("Number of atoms in MOT")
#     plt.plot(fit0_x[2], num_atoms_vs_x[PreviewIndex,:], 'g.', label='Signal')
#     plt.plot(fit0_x[2], fit0_x[1].best_fit, 'b', label='Fit')
#     # plt.xlim(fit0_x[2][0], fit0_x[2][-1])
#     plt.legend()
#     plt.tight_layout()
#     # plt.savefig(folder_name+r"\Horizontal Gaussian Example.png", dpi = 300)

#     fit0_y = Gaussian_fit(num_atoms_vs_y[PreviewIndex,:])
#     plt.figure()
#     plt.title('Atoms TOF vertical example plot, standard dev. = {}m'.format(round(fit0_y[0], 5)))
#     plt.xlabel("Position (m)")
#     plt.ylabel("Number of atoms in MOT")
#     plt.plot(fit0_y[2], num_atoms_vs_y[PreviewIndex,:], 'g.', label='Signal')
#     plt.plot(fit0_y[2], fit0_y[1].best_fit, 'b', label='Fit')
#     # plt.xlim(fit0_y[2][0], fit0_y[2][-1])
#     plt.legend()
#     plt.tight_layout()
#     plt.show()
#     # plt.savefig(folder_name+r"\Vertical Gaussian Example.png", dpi = 300)
    
