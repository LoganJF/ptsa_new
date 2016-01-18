__author__ = 'm'

import numpy as np
import xray
from ptsa.data.common import TypeValTuple, PropertiedObject, get_axis_index
from scipy.signal import resample

from ptsa.wavelet import phase_pow_multi
import time
from ptsa.wavelet import morlet_multi, next_pow2
from scipy.fftpack import fft, ifft


class WaveletFilter(PropertiedObject):
    _descriptors = [
        TypeValTuple('freqs', np.ndarray, np.array([], dtype=np.float)),
        TypeValTuple('time_axis_index', int, -1),
        TypeValTuple('bipolar_pairs', np.recarray, np.recarray((0,), dtype=[('ch0', '|S3'), ('ch1', '|S3')])),
        TypeValTuple('resamplerate', float, -1),
        TypeValTuple('output', str, '')

    ]

    def __init__(self, time_series, **kwds):

        self.window = None
        self.time_series = time_series
        self.init_attrs(kwds)

        self.compute_power_and_phase_fcn=None
        if self.output == 'power':
            self.compute_power_and_phase_fcn = self.compute_power
        elif self.output == 'phase':
            self.compute_power_and_phase_fcn = self.compute_phase
        else:
            self.compute_power_and_phase_fcn = self.compute_power_and_phase



    def all_but_time_iterator(self, array):
        from itertools import product
        sizes_except_time = np.asarray(array.shape)[:-1]
        ranges = map(lambda size: xrange(size), sizes_except_time)
        for cart_prod_idx_tuple in product(*ranges):
            yield cart_prod_idx_tuple, array[cart_prod_idx_tuple]

    def bipolar_iterator(self, array):
        from itertools import product
        sizes_except_time = np.asarray(array.shape)[:-1]

        # depending on the reader, channel axis may be a rec array or a simple array
        # we are interested in an array that has channel labels

        time_series_channel_axis = self.time_series['channels'].data
        try:
            time_series_channel_axis = time_series_channel_axis['name']
        except (KeyError, IndexError):
            pass

        ranges = [xrange(len(self.time_series['events'])), xrange(len(self.bipolar_pairs))]
        for cart_prod_idx_tuple in product(*ranges):
            e, b = cart_prod_idx_tuple[0], cart_prod_idx_tuple[1]
            bp_pair = self.bipolar_pairs[b]

            ch0 = self.time_series.isel(channels=(time_series_channel_axis == bp_pair['ch0']), events=e).values
            ch1 = self.time_series.isel(channels=(time_series_channel_axis == bp_pair['ch1']), events=e).values

            yield cart_prod_idx_tuple, np.squeeze(ch0 - ch1)

    def resample_time_axis(self):
        from ptsa.data.filters.ResampleFilter import ResampleFilter

        rs_time_axis = None  # resampled time axis
        if self.resamplerate > 0:

            rs_time_filter = ResampleFilter(resamplerate=self.resamplerate)
            rs_time_filter.set_input(self.time_series[0, 0, :])
            time_series_resampled = rs_time_filter.filter()
            rs_time_axis = time_series_resampled['time']
        else:
            rs_time_axis = self.time_series['time']

        return rs_time_axis




    def allocate_output_arrays(self, time_axis_size):
        array_type = np.float32
        # if self.output not in ('phase', 'power'):
        #     array_type = np.float32

        if len(self.bipolar_pairs):
            shape = (self.bipolar_pairs.shape[0], self.time_series['events'].shape[0], self.freqs.shape[0],time_axis_size)
        else:
            shape = self.time_series.shape[:-1] + (self.freqs.shape[0], time_axis_size,)

        if self.output == 'power':
            return np.empty(shape=shape, dtype = array_type), None
        elif self.output == 'phase':
            return  None, np.empty(shape=shape, dtype = array_type)
        else:
            return np.empty(shape=shape, dtype = array_type), np.empty(shape=shape, dtype = array_type)

    def resample_power_and_phase(self,pow_array_single,phase_array_single, num_points):

        resampled_pow_array = None
        resampled_phase_array = None

        if self.resamplerate>0.0:
            if pow_array_single is not None:
                resampled_pow_array = resample(pow_array_single, num=num_points)
            if phase_array_single is not None:
                resampled_phase_array = resample(phase_array_single, num=num_points)

        else:
            resampled_pow_array=pow_array_single
            resampled_phase_array=phase_array_single

        return resampled_pow_array,resampled_phase_array


    def compute_power(self,wavelet_coef_array):
        return wavelet_coef_array.real ** 2 + wavelet_coef_array.imag ** 2, None

    def compute_phase(self,wavelet_coef_array):
        return None, np.angle(wavelet_coef_array)

    def compute_power_and_phase(self,wavelet_coef_array):
        return wavelet_coef_array.real ** 2 + wavelet_coef_array.imag ** 2,np.angle(wavelet_coef_array)


    def store_power_and_phase(self, idx_tuple, power_array, phase_array, power_array_single, phase_array_single):

        if power_array_single is not None:
            power_array[idx_tuple] = power_array_single
        if phase_array_single is not None:
            phase_array[idx_tuple] = phase_array_single


    def get_data_iterator(self):
        if len(self.bipolar_pairs):
            data_iterator = self.bipolar_iterator(self.time_series)
        else:
            data_iterator = self.all_but_time_iterator(self.time_series)

        return data_iterator

    def compute_wavelet_ffts(self):

        samplerate = self.time_series.attrs['samplerate']

        freqs = np.atleast_1d(self.freqs)

        wavelets = morlet_multi(freqs=freqs, widths=5, samplerates=samplerate)
        # ADD WARNING HERE FROM PHASE_MULTI

        num_wavelets = len(wavelets)

        # computting length of the longest wavelet
        s_w = max(map(lambda wavelet: wavelet.shape[0], wavelets))
        # length of the tie axis of the time series
        s_d = self.time_series['time'].shape[0]

        # determine the size based on the next power of 2
        convolution_size = s_w + s_d - 1
        convolution_size_pow2 = np.power(2, next_pow2(convolution_size))

        # preallocating arrays
        wavelet_fft_array = np.empty(shape=(num_wavelets, convolution_size_pow2), dtype=np.complex64)

        # computting wavelet ffts
        for i, wavelet in enumerate(wavelets):
            wavelet_fft_array[i] = fft(wavelet, convolution_size_pow2)

        return wavelet_fft_array, convolution_size , convolution_size_pow2

    def filter(self):

        data_iterator = self.get_data_iterator()

        time_axis = self.resample_time_axis()
        time_axis_size =  time_axis.shape[0]

        wavelet_pow_array, wavelet_phase_array = self.allocate_output_arrays(time_axis_size=time_axis_size)

        # preallocating array
        wavelet_coef_single_array = np.empty(shape=(time_axis.shape[0]), dtype=np.complex64)

        wavelet_fft_array, convolution_size, convolution_size_pow2 = self.compute_wavelet_ffts()
        num_wavelets = wavelet_fft_array.shape[0]

        wavelet_start = time.time()

        start_offset = (convolution_size - time_axis.shape[0]) / 2
        end_offset = start_offset + time_axis.shape[0]

        for idx_tuple, signal in data_iterator:

            signal_fft = fft(signal, convolution_size_pow2)

            for w in xrange(num_wavelets):
                signal_wavelet_conv = ifft(wavelet_fft_array[w] * signal_fft)
                wavelet_coef_single_array[:] = signal_wavelet_conv[start_offset:end_offset]

                out_idx_tuple = idx_tuple + (w,)

                pow_array_single, phase_array_single = self.compute_power_and_phase_fcn( wavelet_coef_single_array)

                self.resample_power_and_phase(pow_array_single, phase_array_single, num_points=time_axis_size)

                self.store_power_and_phase(out_idx_tuple,wavelet_pow_array, wavelet_phase_array, pow_array_single, phase_array_single)

        print 'total time wavelet loop: ', time.time() - wavelet_start
        #


def test_1():
    import time
    start = time.time()

    e_path = '/Users/m/data/events/RAM_FR1/R1060M_events.mat'

    from ptsa.data.readers import BaseEventReader

    base_e_reader = BaseEventReader(event_file=e_path, eliminate_events_with_no_eeg=True, use_ptsa_events_class=False)

    base_e_reader.read()

    base_events = base_e_reader.get_output()

    base_events = base_events[base_events.type == 'WORD']

    # selecting only one session
    base_events = base_events[base_events.eegfile == base_events[0].eegfile]

    from ptsa.data.readers.TalReader import TalReader
    tal_path = '/Users/m/data/eeg/R1060M/tal/R1060M_talLocs_database_bipol.mat'
    tal_reader = TalReader(tal_filename=tal_path)
    monopolar_channels = tal_reader.get_monopolar_channels()
    bipolar_pairs = tal_reader.get_bipolar_pairs()

    print 'bipolar_pairs=', bipolar_pairs

    from ptsa.data.readers.TimeSeriesSessionEEGReader import TimeSeriesSessionEEGReader

    # time_series_reader = TimeSeriesSessionEEGReader(events=base_events, channels = ['002', '003', '004', '005'])
    time_series_reader = TimeSeriesSessionEEGReader(events=base_events, channels=monopolar_channels)
    ts_dict = time_series_reader.read()

    first_session_data = ts_dict.items()[0][1]

    print first_session_data

    wavelet_start = time.time()

    wf = WaveletFilter(time_series=first_session_data,
                       bipolar_pairs=bipolar_pairs[0:3],
                       freqs=np.logspace(np.log10(3), np.log10(180), 12),
                       # resamplerate=50.0
                       )

    pow_wavelet = wf.filter()
    print 'wavelet total time = ', time.time() - wavelet_start
    return pow_wavelet

    from ptsa.data.filters.EventDataChopper import EventDataChopper
    edcw = EventDataChopper(events=base_events, event_duration=1.6, buffer=1.0,
                            data_dict={base_events[0].eegfile: pow_wavelet})

    chopped_wavelets = edcw.filter()

    chopped_wavelets = chopped_wavelets.items()[0][1]  # getting first item of return dictionary

    print 'total time = ', time.time() - start
    #
    # from ptsa.data.filters.ResampleFilter import ResampleFilter
    # rsf = ResampleFilter (resamplerate=50.0)
    # rsf.set_input(chopped_wavelets)
    # chopped_wavelets_resampled = rsf.filter()
    #
    # return chopped_wavelets_resampled
    return chopped_wavelets


def test_2():
    import time
    start = time.time()

    e_path = '/Users/m/data/events/RAM_FR1/R1060M_events.mat'

    from ptsa.data.readers import BaseEventReader

    base_e_reader = BaseEventReader(event_file=e_path, eliminate_events_with_no_eeg=True, use_ptsa_events_class=False)

    base_e_reader.read()

    base_events = base_e_reader.get_output()

    base_events = base_events[base_events.type == 'WORD']

    # selecting only one session
    base_events = base_events[base_events.eegfile == base_events[0].eegfile]

    from ptsa.data.readers.TalReader import TalReader
    tal_path = '/Users/m/data/eeg/R1060M/tal/R1060M_talLocs_database_bipol.mat'
    tal_reader = TalReader(tal_filename=tal_path)
    monopolar_channels = tal_reader.get_monopolar_channels()
    bipolar_pairs = tal_reader.get_bipolar_pairs()

    print 'bipolar_pairs=', bipolar_pairs

    from ptsa.data.readers.TimeSeriesEEGReader import TimeSeriesEEGReader

    time_series_reader = TimeSeriesEEGReader(events=base_events, start_time=0.0,
                                             end_time=1.6, buffer_time=1.0, keep_buffer=True)

    base_eegs = time_series_reader.read(channels=monopolar_channels)

    # base_eegs = base_eegs[:, 0:10, :]
    # bipolar_pairs = bipolar_pairs[0:10]


    wf = WaveletFilter(time_series=base_eegs,
                       # bipolar_pairs=bipolar_pairs,
                       freqs=np.logspace(np.log10(3), np.log10(180), 12),
                       # freqs=np.array([3.]),
                       output='power',
                       # resamplerate=50.0
                       )

    pow_wavelet = wf.filter()

    print 'total time = ', time.time() - start

    return pow_wavelet


if __name__ == '__main__':
    edcw = test_2()


# if __name__=='__main__':
#
#
#
#     edcw = test_1()
#     pow_wavelet = test_2()
#
#     import matplotlib;
#     matplotlib.use('Qt4Agg')
#
#
#     import matplotlib.pyplot as plt
#     plt.get_current_fig_manager().window.raise_()
#
#
#
#     # pow_wavelet_res =  resample(pow_wavelet.data[0,1,3,500:-501],num=180)[50:]
#     # edcw_res =  resample(edcw.data[0,1,3,500:-501],num=180)[50:]
#
#     # pow_wavelet_res =  resample(pow_wavelet.data[0,1,3,:],num=180)[50:-50]
#     # edcw_res =  resample(edcw.data[0,1,3,:],num=180)[50:-50]
#
#     pow_wavelet_res =  pow_wavelet.data[0,1,3,50:-50]
#     edcw_res =  edcw.data[0,1,3,50:-50]
#
#
#
#     print
#
#
#
#
#     plt.plot(np.arange(pow_wavelet_res.shape[0]),pow_wavelet_res)
#     plt.plot(np.arange(edcw_res.shape[0])-0.5,edcw_res)
#
#
#     plt.show()
#


# class WaveletFilter(PropertiedObject):
#     _descriptors = [
#         TypeValTuple('freqs', np.ndarray, np.array([],dtype=np.float)),
#         TypeValTuple('time_axis_index', int, -1),
#         TypeValTuple('bipolar_pairs', np.recarray, np.recarray((0,),dtype=[('ch0', '|S3'),('ch1', '|S3')])),
#         TypeValTuple('resamplerate',float,-1)
#
#     ]
#
#
#     def __init__(self,time_series, **kwds):
#
#         self.window = None
#         self.time_series = time_series
#
#         for option_name, val in kwds.items():
#
#             try:
#                 attr = getattr(self,option_name)
#                 setattr(self,option_name,val)
#             except AttributeError:
#                 print 'Option: '+ option_name+' is not allowed'
#
#
#     def filter(self):
#
#         from ptsa.data.filters.ResampleFilter import ResampleFilter
#
#         rs_time_axis = None # resampled time axis
#         if self.resamplerate > 0:
#
#             rs_time_filter = ResampleFilter (resamplerate=self.resamplerate)
#             rs_time_filter.set_input(self.time_series[0,0,:])
#             time_series_resampled = rs_time_filter.filter()
#             rs_time_axis = time_series_resampled ['time']
#         else:
#             rs_time_axis  = self.time_series['time']
#
#
#         pow_array = xray.DataArray(
#             np.empty(
#             shape=(self.bipolar_pairs.shape[0],self.time_series['events'].shape[0],self.freqs.shape[0],rs_time_axis.shape[0]),
#             dtype=np.float64),
#             dims=['bipolar_pair','events','frequency','time']
#         )
#
#
#         # pow_array = xray.DataArray(
#         #     np.empty(
#         #     shape=(self.bipolar_pairs.shape[0],self.time_series['events'].shape[0],self.freqs.shape[0],self.time_series['time'].shape[0]),
#         #     dtype=np.float64),
#         #     dims=['bipolar_pair','events','frequency','time']
#         # )
#
#
#
#
#         # rand_array = np.random.rand(self.bipolar_pairs.shape[0],self.time_series['events'].shape[0],self.freqs.shape[0],self.time_series['time'].shape[0])
#
#
#         # pow_array = xray.DataArray(
#         #     rand_array,
#         #     dims=['bipolar_pair','event','frequency','time']
#         # )
#
#
#         # depending on the reader channel axis may be a rec array or a simple array
#         # we are interested in an array that has channel labels
#         time_series_channel_axis = self.time_series['channels'].data
#         try:
#             time_series_channel_axis = time_series_channel_axis['name']
#         except (KeyError,IndexError):
#             pass
#
#         samplerate = self.time_series.attrs['samplerate']
#
#         for e, ev in enumerate(self.time_series['events']):
#             for b, bp_pair in enumerate(self.bipolar_pairs):
#
#                 print 'bp_pair=',bp_pair, ' event num = ',e
#
#                 ch0 = self.time_series.isel(channels=(time_series_channel_axis == bp_pair['ch0']), events=e).values
#                 ch1 = self.time_series.isel(channels=(time_series_channel_axis == bp_pair['ch1']), events=e).values
#
#                 # ch0 = self.time_series.isel(channels=(time_series_channel_axis == bp_pair['ch0'])).values
#                 # ch1 = self.time_series.isel(channels=(time_series_channel_axis == bp_pair['ch1'])).values
#
#                 # ch0 = self.time_series.isel(channels=(self.time_series['channels']==bp_pair['ch0'])).values
#                 # ch1 = self.time_series.isel(channels=(self.time_series['channels']==bp_pair['ch1'])).values
#
#
#                 bp_data = ch0-ch1
#                 # import time
#                 # time.sleep(0.5)
#
#                 bp_data_wavelet = phase_pow_multi(self.freqs, bp_data, to_return='power', samplerates=samplerate)
#
#                 bp_data_wavelet = np.squeeze(bp_data_wavelet)
#
#                 if self.resamplerate>0.0:
#                     bp_data_wavelet = resample(bp_data_wavelet, num=rs_time_axis.shape[0], axis=1)
#                 # print bp_data_wavelet
#                 #
#
#
#
#                 pow_array[b,e] = bp_data_wavelet
#                 # pow_array[b,e,:,:] = np.squeeze(bp_data_wavelet)[:,:]
#                 # pow_array[b,e,:,:] = -1.0
#                 # if b == 2:
#                 #     break
#         #assigning axes
#         pow_array['frequency'] = self.freqs
#         pow_array['bipolar_pair'] = self.bipolar_pairs
#         pow_array['time'] = rs_time_axis
#
#         pow_array.attrs['samplerate'] = samplerate
#
#         if self.resamplerate>0:
#             pow_array.attrs['samplerate'] = self.resamplerate
#
#
#
#         return pow_array
#





    # def allocate_output_arrays(self, time_axis_size):
    #     array_type = np.float32
    #     if self.output not in ('phase', 'power'):
    #         array_type = np.float32
    #
    #     if self.output in ('phase', 'power'):
    #         if len(self.bipolar_pairs):
    #
    #             wavelet_pow_array = xray.DataArray(
    #                 np.empty(
    #                     shape=(self.bipolar_pairs.shape[0], self.time_series['events'].shape[0], self.freqs.shape[0],
    #                            time_axis_size),
    #                     dtype=array_type),
    #                 dims=['bipolar_pair', 'events', 'frequency', 'time']
    #             )
    #
    #         else:
    #             wavelet_pow_array = xray.DataArray(
    #                 np.empty(
    #                     shape=self.time_series.shape[:-1] + (self.freqs.shape[0], time_axis_size,),
    #                     dtype=array_type),
    #                 dims=['bipolar_pair', 'events', 'frequency', 'time']
    #             )
    #
    #         return wavelet_pow_array, None
    #
    #     else:
    #         if len(self.bipolar_pairs):
    #
    #             wavelet_pow_array = xray.DataArray(
    #                 np.empty(
    #                     shape=(self.bipolar_pairs.shape[0], self.time_series['events'].shape[0], self.freqs.shape[0],
    #                            time_axis_size),
    #                     dtype=array_type),
    #                 dims=['bipolar_pair', 'events', 'frequency', 'time']
    #             )
    #
    #             wavelet_phase_array = xray.DataArray(
    #                 np.empty(
    #                     shape=(self.bipolar_pairs.shape[0], self.time_series['events'].shape[0], self.freqs.shape[0],
    #                            time_axis_size),
    #                     dtype=array_type),
    #                 dims=['bipolar_pair', 'events', 'frequency', 'time']
    #             )
    #
    #         else:
    #             wavelet_pow_array = xray.DataArray(
    #                 np.empty(
    #                     shape=(self.bipolar_pairs.shape[0], self.time_series['events'].shape[0], self.freqs.shape[0],
    #                            time_axis_size),
    #                     dtype=array_type),
    #                 dims=['bipolar_pair', 'events', 'frequency', 'time']
    #             )
    #
    #             wavelet_phase_array = xray.DataArray(
    #                 np.empty(
    #                     shape=(self.bipolar_pairs.shape[0], self.time_series['events'].shape[0], self.freqs.shape[0],
    #                            time_axis_size),
    #                     dtype=array_type),
    #                 dims=['bipolar_pair', 'events', 'frequency', 'time']
    #             )
    #
    #         return wavelet_pow_array, wavelet_phase_array



    # def compute_and_store_power(self, idx_tuple, power_array, phase_array, wavelet_coef_array):
    #
    #     power_array[idx_tuple] = wavelet_coef_array.real ** 2 + wavelet_coef_array.imag ** 2
    #
    # def compute_and_store_phase(self, idx_tuple, power_array, phase_array, wavelet_coef_array):
    #
    #     phase_array[idx_tuple] = np.angle(wavelet_coef_array)
    #
    # def compute_and_store_phase_and_power(self,idx_tuple, power_array, phase_array, wavelet_coef_array):
    #     self.compute_and_store_power(idx_tuple, power_array, phase_array, wavelet_coef_array)
    #     self.compute_and_store_phase(idx_tuple, power_array, phase_array, wavelet_coef_array)


        # def compute_and_store_phase(self, idx_tuple, power_array, phase_array, wavelet_coef_array):
    #
    #     phase_array[idx_tuple] = np.angle(wavelet_coef_array)

    # def get_compute_and_store_output(self):
    #     if self.output == 'power':
    #         return self.compute_and_store_power
    #     elif self.output == 'phase':
    #         return self.compute_and_store_phase
    #     else:
    #         return self.compute_and_store_phase_and_power
