from ctypes import *
import time
from PIL import Image
from scipy import optimize
import sys
import numpy as np
import time
import peakdetect
from scipy import ndimage
from matplotlib import pyplot
from scipy.stats import chisquare
from itertools import product
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet.threads import deferToThread
from labrad.server import LabradServer, setting, Signal
from AndorServer import Andor, AndorServer


class Parameter:
    def __init__(self, value):
            self.value = value

    def set(self, value):
            self.value = value

    def __call__(self):
            return self.value

class AndorIonCount(LabradServer, AndorServer):
    """ Contains methods that count ions in pictures taken by the Andor Luca"""
    
    name = "Andor Ion Count"

    def initServer(self):

        self.listeners = set()  
        self.prepareCamera()
        self.positionDict = {
                            '2':                                  [-.62996, .62996],
                            '3':                                 [-1.0772, 0, 1.0772],
                            '4':                          [-1.4368, -.45438, .45438, 1.4368],
                            '5':                         [-1.7429, -0.8221, 0, 0.8221, 1.7429],
                            '6':                  [-2.0123, -1.4129, -.36992, .36992, 1.4129, 2.0123],
                            '7':                 [-2.2545, -1.1429, -.68694, 0, .68694, 1.1429, 2.2545],
                            '8':           [-2.4758, -1.6621, -.96701, -.31802, .31802, .96701, 1.6621, 2.4758],
                            '9':         [-2.6803, -1.8897, -1.2195, -.59958, 0, .59958, 1.2195, 1.8897, 2.6803],
                            '10': [-2.8708, -2.10003, -1.4504, -.85378, -.2821, .2821, .85378, 1.4504, 2.10003, 2.8708]
                            }        

    def initContext(self, c):
        """Initialize a new context object."""
        self.listeners.add(c.ID)
    
    def expireContext(self, c):
        self.listeners.remove(c.ID)
        
    def getOtherListeners(self,c):
        notified = self.listeners.copy()
        notified.remove(c.ID)
        return notified
    
    def GetAverageDarkIons(self, darkIonCatalog, numKin, iterations):
        totalNumberImagesAnalyzed = ((numKin / iterations) - 1) * iterations # = numKin - iterations # this excludes the 'initial' images
        return (np.sum(darkIonCatalog) / totalNumberImagesAnalyzed)         
    
    def BuildDarkIonCatalog(self, peakPositionCatalog, iterations, numKin):
        """ Returns a list of numbers of dark ions in each image (in order). 

           ionPositionCatalog is a list of lists of peak positions
            
            Ex:
                peakPositionCatalog[1st iteration] = [[peak positions background], [peak positions analyzed image], [peak positions analyzed image]]
                
                len(peakPositionCatalog[0][1]) = number of dark ions for the first image to be analyzed
                
        """
        
        print peakPositionCatalog
        
        numberImagesInSet = (numKin / iterations)
        
        darkIonCatalog = []
        
        for iteration in np.arange(iterations):
            for image in np.arange(1,numberImagesInSet): # skip the background images
                darkIonCatalog.append(len(peakPositionCatalog[iteration][image]))
        
        return darkIonCatalog
    
    def GetIonNumberCatalog(self, image, darkIonPositionCatalog, iterations, kinSet, numKin):
        """image = 1, 2, or 3 
        
           Note: the array is in order of kinetic set and iteration
        """
        
        numberKineticSets = kinSet
        
        ionNumberCatalog = []
        
        for kinSet in np.arange(numberKineticSets):
            for iteration in np.arange(iterations):
                ionNumberCatalog.append(len(darkIonPositionCatalog[kinSet][iteration][image - 1]))
        
        return ionNumberCatalog
        
#        totalNumberImagesAnalyzed = ((numKin / iterations) - 1) * iterations # = numKin - iterations # this excludes the 'initial' images
#        return (np.sum(darkIons) / totalNumberImagesAnalyzed) 
    
    def GetNumberSwaps(self, ionSwapCatalog):
        """returns the number of instances an ion moves a distance of one ion after heating """
        return (len(np.where(ionSwapCatalog == 1)))
    
    def BuildIonSwapCatalog(self, darkIonPositionCatalog, kinSet, iterations, expectedNumberOfIons):
        """  returns a 1D array describing the distance an ion travelled by comparing the initial
             and final images.
         
             this assumes 2 images to be analyzed per background image. Also assumes that there is 
             only ONE dark ion in both images.
             
             Note: the array is in order of kinetic set
             
         """
        
       
        numberKineticSets = kinSet
        ionSwapCatalog = []
        
        for kinSet in np.arange(numberKineticSets):
            for imageSet in np.arange(iterations):
                if (len(darkIonPositionCatalog[kinSet][imageSet][0]) == 1):
                    initialPosition = darkIonPositionCatalog[kinSet][imageSet][0]
                    if (len(darkIonPositionCatalog[kinSet][imageSet][1]) == 1):
                        finalPosition = darkIonPositionCatalog[kinSet][imageSet][1]                  
                        ionSwapCatalog.append(abs(finalPosition - initialPosition))
                
                print 'number dark ions in first image: ', len(darkIonPositionCatalog[kinSet][imageSet][0])
                print 'number dark ions in second image: ', len(darkIonPositionCatalog[kinSet][imageSet][1])

#        print 'ion swap catalog:'
#        print ionSwapCatalog
        print 'len of ion swap catalog: ', len(ionSwapCatalog)
        return ionSwapCatalog
    
    def BuildIonPositionCatalog(self, peakPositionCatalog, iterations, kinSet, numKin, peakVicinity):
        """
        ionPositionCatalog is a list of lists of ion positions in the chain

        This catalog is built by assuming that each background image has the correct number of ions. The dark ion positions are
        determined by comparing the peak positions of the dark ions to the peak positions of the background image; if they fall within
        a certain 'peakVicinity,' then the dark ion is assigned the same position as one of the background ions.
        
        Ex:    (5 ions)
            
            peakPositionCatalog[1st iteration] = [[12, 26, 39, 53, 68], [24], [41]]
            ionPositionCatalog[1st iteration] = [5, 1, 2]
            
                                                 ^  ^
                                                 |  | --> dark ion position in [0, 1, 2, 3, 4]
                                            range of ions Ex: range(5) -> ion positions: [0, 1, 2, 3, 4]
                                            
            
        Note: len(ionPositionCatalog[0][1]) = number of dark ions for the first image to be analyzed
        
        """
        numberKineticSets = kinSet
        numberImagesInSet = (numKin / iterations)

        
        ionPositionCatalog = [[[] for i in range(iterations)] for j in range(numberKineticSets)] 
        #ionPositionCatalog = np.zeros_like(peakPositionCatalog)

        for kinSet in np.arange(numberKineticSets):
            for imageSet in np.arange(iterations):
                #ionPositionCatalog[imageSet][0] = len(peakPositionCatalog[imageSet][0]) #background image
                ionPositionCatalog[kinSet][imageSet].append(len(peakPositionCatalog[kinSet][imageSet][0])) #background image
                for image in np.arange(1, numberImagesInSet):
                    if (len(peakPositionCatalog[kinSet][imageSet][image]) != 0):
                        for peakPosition in peakPositionCatalog[kinSet][imageSet][image]:
                            result = np.where(abs(np.subtract(peakPositionCatalog[kinSet][imageSet][0], peakPosition)) <= peakVicinity)[0]
                            # assumes that one dark ion will never be close enough to multiple initial ion position
                            if (len(result) != 0):
                                try:
        #                            print 'result[0]'
        #                            print result[0]
                                    #ionPositionCatalog[imageSet][image] = result[0]
                                    ionPositionCatalog[kinSet][imageSet].append(result[0])
                                except:
                                    print 'la gente esta muy loca!'
                            else:
                                ionPositionCatalog[kinSet][imageSet].append(-2) # -2 means no dark ions near initial positions
                                print 'Found a dark ion, but nowhere near the ions in the initial image!'
                    else:
                        ionPositionCatalog[kinSet][imageSet].append(-1) # -1 means no dark ions
                        print 'no dark ions :('

        print 'ion position catalog: '
        print ionPositionCatalog
        return ionPositionCatalog
                
    
    def GetPeakPositionCatalog(self, kinSet, numKin, rows, cols, typicalIonDiameter, initialThreshold, darkThreshold, iterations):
        """This method counts the number of dark ions (and their positions) in 
            an ion chain. It is required that the background image contain a 
            fully illuminated chain of ions.
        
            numkin - total number of images in the data array.    
           
           This method assumes that for each background image taken, there is
           ((numKin / iterations) - 1) images for comparison.
           
           Example: numKin = 50, iterations = 10
                    for each background image, the following 4 images will be
                    analyzed against it.
                    
                    (1 + 4) * 10 = 50
                    
                    1 background, 4 images.
                    
                    Therefore: 10 'sets' of 5 images.
                    
            NOTE: Assumes data exists in AndorServer's imageArray
                    
        """
        numberKineticSets = kinSet
        numberImagesInSet = (numKin / iterations)
        numberImagesToAnalyze = (numKin / iterations) - 1
        
        
        # 3D array of each image
        try:
            data = np.reshape(np.array(self.camera.imageArray), (kinSet, numKin, rows, cols))
        except ValueError:
            raise Exception("Trying to analyze more images than there is in the data? Image region correct?")
#        data = self.imageArray
        
#        ###### TESTING TESTING TESTING 123 ################
#        rawdata1 = np.loadtxt(r'C:\Users\lattice\Downloads\testandor\count-5ions-sample-dark\s60001.asc')
#        rawdata1 = rawdata1.transpose()
#        
#        rawdata2 = np.loadtxt(r'C:\Users\lattice\Downloads\testandor\count-5ions-sample-dark\s60002.asc')
#        rawdata2 = rawdata2.transpose()
#
#        rawdata3 = np.loadtxt(r'C:\Users\lattice\Downloads\testandor\count-5ions-sample-dark\s60003.asc')
#        rawdata3 = rawdata3.transpose()
#        
#        
##        #dark ion count
##        arr = [[] for i in range(4)]
##        arr[0] = rawdata1
##        arr[1] = rawdata3
##        arr[2] = rawdata1
##        arr[3] = rawdata2
#
#     
#        # ion swap
#        arr = [[] for i in range(6)]
#        arr[0] = rawdata1
#        arr[1] = rawdata2
#        arr[2] = rawdata3
#        arr[3] = rawdata1
#        arr[4] = rawdata1
#        arr[5] = rawdata3
#                        
#        data = np.array(arr)
#        
#        ###### TESTING TESTING TESTING 123 ################
        
        peakPositionCatalog = [[[] for i in range(iterations)] for j in range(kinSet)] 
        
        """ peakPositionCatalog is a list of list of lists of peak positions
            
            Ex:
                peakPositionCatalog[1st kinetic set][1st iteration] = [[peak positions initial], [peak positions analyzed image], [peak positions analyzed image]]
                
                len(peakPositionCatalog[0][0][1]) = number of dark ions for the first analyzed image in the first kinetic set
            
        """
        
        #for loop here over kinset?
        for kinSet in np.arange(numberKineticSets):
            for imageSet in np.arange(iterations):
                sumArray = []
                for image in np.arange(numberImagesInSet):
                    """ The image, assumed to be have more columns than rows, will first be analyzed
                        in the axial direction. The sums of the intensities will be collected in the
                        axial direction first. This will help narrow down which section of the image,
                        in order to exclude noise.
                        
                        Example:   |  [[ # # # # # # # # # # # # # # # # # # # # # #],       |
                                   0   [ # # # # # # # # # # # # # # # # # # # # # #], avgIonDiameter
                                   |   [ # # # # # # # # # # # # # # # # # # # # # #],       |
                                  |    [ * * * * * * * * * * * * * * * * * * * * * *], <-- strip of highest intensity,
                                  1    [ * * * * * * * * * * * * * * * * * * * * * *], <-- will only be used for 
                                  |    [ * * * * * * * * * * * * * * * * * * * * * *], <-- proceeding calculations
                                   |   [ % % % % % % % % % % % % % % % % % % % % % %],
                                   2   [ % % % % % % % % % % % % % % % % % % % % % %],
                                   |   [ % % % % % % % % % % % % % % % % % % % % % %]]
                                              
                                                         Axial   
                    """
                    
                    
                    axialSumSegments = []
                    axialData = np.sum(data[kinSet][numberImagesInSet*imageSet + image], 1) # 1D vector: sum of intensities in the axial direction. length = rows
    
                    
                    """ choose each strip by only analyzing the 1D vector of sums
                        
                        [ # # # * * * % % %] -> [# * %]
                                                 0 1 2
                                  ^                ^
                                  |                |
                                Segment           most
                                                intense
                                                  sum
                    """
                    intensitySum = 0
                    cnt = 0
                    for i in np.arange(rows):
                        intensitySum += axialData[i]
                        cnt += 1
                        if (cnt == typicalIonDiameter):
                            axialSumSegments.append(intensitySum)
                            cnt = 0
                            intensitySum = 0 
                            
                    # find the index of the strip with the highest intensity
                    mostIntenseRegionIndex = np.where(axialSumSegments == np.max(axialSumSegments))[0][0]
                    
                    """ use this strip to create the 1-dimensional array of intensity sums in the radial direction
                    
                        [ * * * * * * * * * * * * * * * * * * * * * *] 1D vector of sums
                                                                        in the radial direction
                                              ^                            length = cols
                                              |                        Used to find peaks
                       
                       [[ * * * * * * * * * * * * * * * * * * * * * *], most 
                        [ * * * * * * * * * * * * * * * * * * * * * *], intense
                        [ * * * * * * * * * * * * * * * * * * * * * *]]  strip
                        
                        
                    
                    """
    
    
                    mostIntenseData = data[kinSet][numberImagesInSet*imageSet + image][(mostIntenseRegionIndex*typicalIonDiameter):(mostIntenseRegionIndex*typicalIonDiameter + typicalIonDiameter), :]
                    mostIntenseDataSums = np.sum(mostIntenseData, 0) / typicalIonDiameter #1D vector
                    
                    """
                              |      |      |      |      |
                        _____/|\____/|\____/|\____/|\____/|\_____   background image sum
                        
                        
                        ___________________   ___________________   dark ion image sum (background subtracted out)
                                           \|/
                                            |
                    
                    """
                    
                    sumArray.append(mostIntenseDataSums)
    
                ########### find the number of ions, peak positions of initial image ########### 
                initialDenoised = ndimage.gaussian_filter(sumArray[0], 2)    
                initialMaxPeaks, initialMinPeaks = peakdetect.peakdetect(initialDenoised, range(cols), 1, 1)
                initialPeakPositions = []
                for peak in initialMaxPeaks: # peak = [position (pixel), intensity]
                    if peak[1] > initialThreshold:
                        initialPeakPositions.append(peak[0])
    #            print 'initial peak positions: ', initialPeakPositions
    #            print 'number of ions: ', len(initialPeakPositions)
                
                peakPositionCatalog[kinSet][imageSet].append(initialPeakPositions)
                
                ########### find the number of dark ions, peak positions of analyzed images ###########
                for image in np.arange(numberImagesToAnalyze):
                    subtractedData = sumArray[(image+1)] - sumArray[0]
                    subtractedDataDenoised = ndimage.gaussian_filter(subtractedData, 2)
                    darkMaxPeaks, darkMinPeaks = peakdetect.peakdetect(subtractedDataDenoised, range(cols), 1, 1)
                    darkPeakPositions = []
                    for peak in darkMinPeaks:
                        if peak[1] < darkThreshold:
                            darkPeakPositions.append(peak[0])
    
    #                print 'initial dark peak positions: ', darkPeakPositions
    #                print 'number of dark ions: ', len(darkPeakPositions)
                    peakPositionCatalog[kinSet][imageSet].append(darkPeakPositions) # we're hoping there is only one peak here!
            
               
        print 'peak positionn catalog:'
        print peakPositionCatalog
        return peakPositionCatalog    






    def _fit(self, function, parameters, expectedNumberOfIons, y, x = None):  
        if x is None: x = np.arange(y.shape[0])
        return optimize.leastsq((y - function(x, parameters, expectedNumberOfIons)), parameters)
    
    def _fitFunction(self, x, p, expectedNumberOfIons):
        """p = [height, alpha, axialOffset, sigma, offset] """   
        fitFunc = 0
        for i in self.positionDict[str(expectedNumberOfIons)]:
            fitFunc += p[0]*np.exp(-(((x-i*p[1] - p[2])/p[3])**2)/2)
    #    fitFunc = offset() + height()*exp(-(((x+1.7429*alpha())/sigma())**2)/2) + height()*exp(-(((x+0.8221*alpha())/sigma())**2)/2) + height()*exp(-(((x)/sigma())**2)/2) + height()*exp(-(((x-0.8221*alpha())/sigma())**2)/2) + height()*exp(-(((x-1.7429*alpha())/sigma())**2)/2)
        return fitFunc + p[4]
    
    def _getOneDDdata(self, data, rows, cols, typicalIonDiameter):
        """ The image, assumed to be have more columns than rows, will first be analyzed
            in the axial direction. The sums of the intensities will be collected in the
            axial direction first. This will help narrow down which section of the image,
            in order to exclude noise.
            
            Example:   |  [[ # # # # # # # # # # # # # # # # # # # # # #],       |
                       0   [ # # # # # # # # # # # # # # # # # # # # # #], avgIonDiameter
                       |   [ # # # # # # # # # # # # # # # # # # # # # #],       |
                      |    [ * * * * * * * * * * * * * * * * * * * * * *], <-- strip of highest intensity,
                      1    [ * * * * * * * * * * * * * * * * * * * * * *], <-- will only be used for 
                      |    [ * * * * * * * * * * * * * * * * * * * * * *], <-- proceeding calculations
                       |   [ % % % % % % % % % % % % % % % % % % % % % %],
                       2   [ % % % % % % % % % % % % % % % % % % % % % %],
                       |   [ % % % % % % % % % % % % % % % % % % % % % %]]
                                  
                                             Axial   
        """
        
        
        axialSumSegments = []
        axialData = np.sum(data, 1) # 1D vector: sum of intensities in the axial direction. length = rows

        
        """ choose each strip by only analyzing the 1D vector of sums
            
            [ # # # * * * % % %] -> [# * %]
                                     0 1 2
                      ^                ^
                      |                |
                    Segment           most
                                    intense
                                      sum
        """
        intensitySum = 0
        cnt = 0
        for i in np.arange(rows):
            intensitySum += axialData[i]
            cnt += 1
            if (cnt == typicalIonDiameter):
                axialSumSegments.append(intensitySum)
                cnt = 0
                intensitySum = 0 
                
        # find the index of the strip with the highest intensity
        mostIntenseRegionIndex = np.where(axialSumSegments == np.max(axialSumSegments))[0][0]
        
        """ use this strip to create the 1-dimensional array of intensity sums in the radial direction
        
            [ * * * * * * * * * * * * * * * * * * * * * *] 1D vector of sums
                                                            in the radial direction
                                  ^                            length = cols
                                  |                        Used to find peaks
           
           [[ * * * * * * * * * * * * * * * * * * * * * *], most 
            [ * * * * * * * * * * * * * * * * * * * * * *], intense
            [ * * * * * * * * * * * * * * * * * * * * * *]]  strip
            
            
        
        """


        mostIntenseData = data[(mostIntenseRegionIndex*typicalIonDiameter):(mostIntenseRegionIndex*typicalIonDiameter + typicalIonDiameter), :]
        mostIntenseDataSums = np.sum(mostIntenseData, 0) / typicalIonDiameter #1D vector
        
        return mostIntenseDataSums
        
    
    def _fitInitialImage(self, kinSet, rows, cols, typicalIonDiameter, expectedNumberOfIons):
        
        parametersArray = []
        
        initialImageArray = self.camera.GetAcquiredData()
        data = np.reshape(initialImageArray, (kinSet, rows, cols))        
        
        for kineticSet in np.arange(kinSet):
            axialSums = self._getOneDDdata(data[kineticSet], rows, cols, typicalIonDiameter)
            
            
            # start here
            xmodel = np.arange(len(axialSums), dtype=float)
        
            global alpha
            global beta
            global offset
            global height
            global sigma        
            alpha = Parameter(15)
            axialOffset = Parameter(33)
            offset = Parameter(np.min(axialSums))
            height = Parameter(np.max(axialSums) - np.min(axialSums))
            sigma = Parameter(5)        
        
            alpha, axialOffset, offset, height, sigma = self._fit(self._fitFunction, [height, alpha, axialOffset, sigma, offset], expectedNumberOfIons, axialSums)
            print 'alpha: ', alpha
            print 'axialOffset: ', axialOffset
            print 'offset: ', offset
            print 'height: ', height
            print 'sigma: ', sigma
            
            ymodel = self._fitFunction(xmodel, [alpha, axialOffset, offset, height, sigma], expectedNumberOfIons)
            
#            pyplot.plot(xmodel, axialSums)
#            pyplot.plot(xmodel, ymodel)
            parametersArray.append([alpha, axialOffset, offset, height, sigma])
        return parametersArray       
    
    def _BuildDarkIonPositionCatalog(self, parametersArray, kinSet, numKin, rows, cols, typicalIonDiameter, expectedNumberOfIons, iterations):
        
        """parametersArray[1st kinetic set] = [height, alpha, axialOffset, sigma, offset]
       
        darkIonPositionCatalog is a list of lists of ion positions in the chain

        This catalog is built by assuming that each background image has the correct number of ions. The dark ion positions are
        determined by comparing the peak positions of the dark ions to the peak positions of the background image; if they fall within
        a certain 'peakVicinity,' then the dark ion is assigned the same position as one of the background ions.
        
        Ex:    (5 ions)
            
            darkIonPositionCatalog[1st kinetic set][1st iteration][1st image] =    [1, 2] --> means two dark ions at positions 1 and 2 in the ion chain
            
                                                                                    ^
                                                                                    | --> dark ion position in [0, 1, 2, 3, 4]
                                                                            
            
        Note: len(darkIonPositionCatalog[0][1]) = number of dark ions for the first image to be analyzed
        
        """        
        
        try:
            data = np.reshape(np.array(self.camera.imageArray), (kinSet, numKin, rows, cols))
        except ValueError:
            raise Exception("Trying to analyze more images than there is in the data? Image region correct?")

        numberImagesInSet = (numKin / iterations) # better equal 2 for ionSwap

        darkIonPositionCatalog = [[[] for i in range(iterations)] for j in range(kinSet)]

        xmodel = np.arange(cols, dtype=float)
        
        for kineticSet in np.arange(kinSet):
            for imageSet in np.arange(iterations):
                for image in np.arange(numberImagesInSet):
                    axialSums = self._getOneDDdata(data[kineticSet][numberImagesInSet*imageSet + image], rows, cols, typicalIonDiameter) 
                    
                    
                    t1 = time.clock()
                    bestFitIonArrangement = [] # 1 = bright, 0 = dark, Ex: (1, 1, 0, 1, 1)
                    bestChiSquare = float(10000000) # get rid of this in the future and make the if statement a try/except
                    positionValues = self.positionDict[str(expectedNumberOfIons)]
                    for ionArrangement in product(range(2), repeat=expectedNumberOfIons):
                        # build the model function, expected to have at least one component = 0 (have an ion dark in the model function)
                        darkModel = 0
                        for ion in np.arange(expectedNumberOfIons):
                            if ionArrangement[ion] == 1:
                                print ionArrangement, ion
                                print positionValues[ion]
                                darkModel += parametersArray[kineticSet][0]*np.exp(-(((xmodel-positionValues[ion]*parametersArray[kineticSet][1] - parametersArray[kineticSet][2])/parametersArray[kineticSet][3])**2)/2)
                        
                        darkModel += parametersArray[kineticSet][4]
                        
                        try:
                            tempChiSquare, pValue = chisquare(axialSums, darkModel)
                            if (tempChiSquare < bestChiSquare):
                                bestChiSquare = tempChiSquare
                                bestFitIonArrangement = ionArrangement
                        except AttributeError:
                            print 'loca!'
                    t2 = time.clock()
                    print 'time: ', (t2-t1)
                    print 'best: ', bestChiSquare, bestFitIonArrangement
                    darkIonPositions = np.where(bestFitIonArrangement == 0)[0] # awesome
                    print darkIonPositions
                    darkIonPositionCatalog[kineticSet][imageSet].append(darkIonPositions)
        
        return darkIonPositionCatalog        
              
            
    @setting(40, "Collect Data", height = 'i', width = 'i', iterations = 'i', numAnalyzedImages = 'i', returns = '')
    def collectData(self, c, height, width, iterations, numAnalyzedImages):
        """Given the iterations, will return the average number of ions"""
        self.camera.GetStatus()
        status = self.camera.status
        if (status == 'DRV_IDLE'):
            numKin = (numAnalyzedImages + 1)*iterations # Number of images in kinetic series = numAnalyzedImages + the background image 
            self.camera.SetAcquisitionMode(3)
            self.camera.SetNumberKinetics(numKin)
#            self.camera.SetKineticCycleTime(0.01)
            print 'Starting Acquisition (Ion Count)'
            yield deferToThread(self.camera.StartAcquisitionKineticExternal)
#            yield self.camera.GetAcquiredDataKinetic(numKin)
            print 'Started!'
                                    
        else:
            raise Exception(status)
        
    @setting(41, "Get Dark Ion Catalog", numKin = 'i', rows = 'i', cols = 'i', typicalIonDiameter = 'i', initialThreshold = 'i', darkThreshold = 'i', iterations = 'i', returns = '*i')
    def getDarkIonCatalog(self, c, numKin, rows, cols, typicalIonDiameter, initialThreshold, darkThreshold, iterations):
        peakPositionCatalog = self.GetPeakPositionCatalog(numKin, rows, cols, typicalIonDiameter, initialThreshold, darkThreshold, iterations)
        darkIonCatalog = self.BuildDarkIonCatalog(peakPositionCatalog, iterations, numKin)
        #avgNumberDarkIons = self.GetAverageDarkIons(darkIonCatalog, numKin, iterations)
        return darkIonCatalog
    
    @setting(42, "Get Ion Position Catalog", numKin = 'i', rows = 'i', cols = 'i', typicalIonDiameter = 'i', initialThreshold = 'i', darkThreshold = 'i', iterations = 'i', peakVicinity = 'i', returns = '')
    def getIonPositionCatalog(self, c, numKin, rows, cols, typicalIonDiameter, initialThreshold, darkThreshold, iterations, peakVicinity):
        peakPositionCatalog = self.GetPeakPositionCatalog(numKin, rows, cols, typicalIonDiameter, initialThreshold, darkThreshold, iterations)
        ionPositionCatalog = self.BuildIonPositionCatalog(peakPositionCatalog, iterations, numKin, peakVicinity)
        print ionPositionCatalog
        #ionSwapCatalog = self.BuildIonSwapCatalog(ionPositionCatalog, iterations)
        #numIonSwaps = self.GetNumberSwaps(ionSwapCatalog)
    
    @setting(43, "Get Ion Number Histogram", image = 'i', kinSet = 'i', numKin = 'i', rows = 'i', cols = 'i', iterations = 'i', returns = '*i')
    def getIonNumberHistogram(self, c, image, kinSet, numKin, rows, cols, iterations):        
        """For Ion Swap, image should = 1, 2 or 3 """
        ionNumberCatalog = self.GetIonNumberCatalog(image, self.darkIonPositionCatalog, iterations, kinSet, numKin)
        if (len(ionNumberCatalog) != 0):
            return ionNumberCatalog
        else:
            raise Exception("There are no ions!")
        
    @setting(44, "Get Ion Swap Histogram", iterations = 'i', kinSet = 'i', numKin = 'i', expectedNumberOfIons = 'i', returns = '*i')
    def getIonSwapHistogram(self, c, iterations, kinSet, numKin, expectedNumberOfIons):
        ionSwapCatalog = self.BuildIonSwapCatalog(self.darkIonPositionCatalog, kinSet, iterations, expectedNumberOfIons)
        if (len(ionSwapCatalog) != 0):
            return np.array(ionSwapCatalog)
        else:
            raise Exception("There are no ions!")     
        
    @setting(45, "Build Dark Ion Position Catalog", kinSet = 'i', numKin = 'i', rows = 'i', cols = 'i', typicalIonDiameter = 'i', expectedNumberOfIons = 'i', iterations = 'i', returns = '')
    def buildDarkIonPositionCatalog(self, c, kinSet, numKin, rows, cols, typicalIonDiameter, expectedNumberOfIons, iterations):
        parametersArray = self._fitInitialImage(kinSet, rows, cols, typicalIonDiameter, expectedNumberOfIons)
        self.darkIonPositionCatalog = self._BuildDarkIonPositionCatalog(parametersArray, kinSet, numKin, rows, cols, typicalIonDiameter, expectedNumberOfIons, iterations)
        print self.darkIonPositionCatalog
        #ionSwapCatalog = self.BuildIonSwapCatalog(ionPositionCatalog, iterations)
        #numIonSwaps = self.GetNumberSwaps(ionSwapCatalog)

        
if __name__ == "__main__":
    from labrad import util
    util.runServer(AndorIonCount())