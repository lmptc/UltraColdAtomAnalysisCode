# -*- coding: utf-8 -*-
"""
Created on Wed Apr 12 14:34:22 2023

@author: Sommer Lab
"""
from ImageAnalysis import ImageAnalysisCode
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import rotate

data_location = r'C:/Users/Sommer Lab/Documents/Data/'

####################################
#Set the date and the folder name
####################################
date = r'/2023/08-2023/08 Aug 2023'
data_folder = r'/Andor/ODT Align'

data_folder = data_location + date + data_folder

####################################
#Parameter Setting
####################################
repetition = 1 #The number of identical runs to be averaged. 
examNum = 5 #The number of runs to exam.
examFrom = None #Set to None if you want to check the last several runs. 
subtract_bg = True
signal_feature = 'wide'
do_plot = True
uniformscale = 0

pictureToHide = []

rowstart = 10
rowend = -10
columnstart = 10
columnend = -10

# rowstart = 75
# rowend = 200
# columnstart = 170
# columnend = 400

####################################
####################################

examNum = examNum * repetition

if examFrom is None:
    examFrom = -examNum
else:
    examFrom = examFrom * repetition
    
examUntil = examFrom + examNum
if examUntil == 0:
    examUntil = None

t_exp = 10e-6
picturesPerIteration = 3
ms = 1e-3

class SIUnits:
    m = 1.0
    um = 1e-6*m
units=SIUnits()

params = ImageAnalysisCode.ExperimentParams(t_exp = t_exp, picturesPerIteration= picturesPerIteration, cam_type = "zyla")      
images_array = ImageAnalysisCode.LoadSpooledSeries(params = params, data_folder=data_folder)
images_array = images_array[examFrom: examUntil]

if len(pictureToHide) > 0:
    images_array = np.delete(images_array, pictureToHide, 0)

# ImageAnalysisCode.ShowImagesTranspose(images_array)

Number_of_atoms, N_abs, ratio_array, columnDensities, deltaX, deltaY = ImageAnalysisCode.absImagingSimple(images_array, 
                firstFrame=0, correctionFactorInput=1.0,  
                subtract_burntin=0, preventNAN_and_INF=True)
# plt.figure()
# plt.imshow(np.array(images_array[0][0]-images_array[0][2],dtype=np.float64)/(images_array[0][1]-images_array[0][2]),vmin=0,vmax=1.1)
# plt.imshow(images_array[0][0]-images_array[0][1])

imgNo = len(columnDensities)
angle_deg= 2 #rotates ccw

AtomNumbers=[]
widths_x = []
widths_y = []

if do_plot == True:
    fig, axs = plt.subplots(imgNo,3, figsize=(3.2*3, 2*imgNo), squeeze = False)
    plt.subplots_adjust(hspace=0.14, wspace=0.12)
    
if uniformscale:
    vmax = columnDensities.max()
    vmin = columnDensities.min()
else:
    vmax = None
    vmin = None

for ind in range(imgNo):
    rotated_ = rotate(columnDensities[ind], angle_deg, reshape = False)[rowstart:rowend,columnstart:columnend]
    # rotated_=columnDensities[ind]
    if ind==0: #first time
        rotated_columnDensities =np.zeros((imgNo, *np.shape(rotated_)))
    rotated_columnDensities[ind] = rotated_

    #preview:
    dx=params.camera.pixelsize_meters/params.magnification  
    print(dx)
    
    popt0, popt1 = ImageAnalysisCode.fitgaussian2D(rotated_columnDensities[ind], dx=dx, 
                                                  do_plot = do_plot, ax=axs[ind], Ind=ind, imgNo=imgNo,
                                                  subtract_bg = subtract_bg, signal_feature = signal_feature, 
                                                  vmax = vmax, vmin = vmin,
                                                  title="1D density", title2D="column density",
                                                  xlabel1D="position ($\mu$m)", ylabel1D="1d density (atoms/$\mu$m)",                                                  
                                                  xscale_factor=1/units.um, yscale_factor=units.um)
        
    if popt0 is not None and popt1 is not None:
        wx = abs(popt0[2])
        AtomNumberX = popt0[0]* wx*(2*np.pi)**0.5 
        
        wy = abs(popt1[2])
        AtomNumberY = popt1[0]* wy*(2*np.pi)**0.5 
        
        AtomNumbers.append(AtomNumberY)
        print("\n{}. Atom Number from gauss fit = {:.2e}".format(ind, AtomNumberY))
        width_x = popt0[2]/units.um
        width_y = popt1[2]/units.um
        print("RMS cloud size x: {:.2f} um".format(width_x))
        print("RMS cloud size y: {:.2f} um".format(width_y))
    
        widths_x.append(width_x)
        widths_y.append(width_y)

fig.tight_layout()

print('\nThe average number of atoms:{:.2e}'.format(np.mean(AtomNumbers)))
    
print("Mean RMS width x: {:.2f} +/- {:.2f} um".format(np.mean(widths_x), np.std(widths_x)))
print("Mean RMS width y: {:.2f} +/- {:.2f} um".format(np.mean(widths_y), np.std(widths_y)))


fig, ax1 = plt.subplots()
ax2 = ax1.twinx()

if repetition > 1:
    widths_y = np.array(widths_y).reshape(-1, repetition)
    AtomNumbers = np.array(AtomNumbers).reshape(-1, repetition)
    
    widths_y_std = widths_y.std(axis=1)
    AtomNumbers_std = AtomNumbers.std(axis=1)
    
    widths_y = widths_y.mean(axis=1)
    AtomNumbers = AtomNumbers.mean(axis=1)
else:
    widths_y_std = None
    AtomNumbers_std = None

xx = np.arange(len(widths_y))

ax1.errorbar(xx, widths_y, widths_y_std, capsize=8, color='tab:orange')
ax1.plot(xx, widths_y, '.', color='tab:orange')
ax1.set_ylabel('Y Widths (µm)', color='tab:orange')
ax1.tick_params(axis="y", labelcolor='tab:orange')

ax2.errorbar(xx, AtomNumbers, AtomNumbers_std, capsize=5, color='tab:green')
ax2.plot(xx, AtomNumbers, '.-', color='tab:green')
ax2.set_ylabel('Atom Number', color='tab:green')
ax2.tick_params(axis="y", labelcolor='tab:green')


# fig, ax1 = plt.subplots()
# ax2 = ax1.twinx()

# ax1.plot(xx, widths_y, '.-', color='tab:orange')
# ax1.set_ylabel('Y Widths (µm)', color='tab:orange')
# ax1.tick_params(axis="y", labelcolor='tab:orange')

# ax2.plot(xx, AtomNumbers, '.-', color='tab:green')
# ax2.set_ylabel('Atom Number', color='tab:green')
# ax2.tick_params(axis="y", labelcolor='tab:green')

fig.tight_layout()
plt.show()


#Temperature fit
# popt, pcov = ImageAnalysisCode.thermometry1D(params, rotated_columnDensities, tof_array, thermometry_axis="y", 
#                                              do_plot = True, save_folder = data_folder)

# popt, pcov = ImageAnalysisCode.thermometry1D(params, rotated_columnDensities, tof_array, thermometry_axis="x", 
#                                              do_plot = True, save_folder = data_folder)