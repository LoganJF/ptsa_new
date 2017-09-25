from ptsa.test.utils import get_rhino_root,skip_without_rhino
import os.path as osp
import unittest,pytest
import h5py
import numpy as np
from ptsa.data.readers.H5RawReader import H5RawReader
from ptsa.data.readers.BaseRawReader import BaseRawReader
from ptsa.data.readers.CMLEventReader import CMLEventReader
from ptsa.data.readers import EEGReader
import time


channels = np.array(['%.03d'%i for i in range(1,10)])

@skip_without_rhino
class TestH5Reader(unittest.TestCase):
    def setUp(self):
        root = get_rhino_root()
        self.h5_dataroot = osp.join(root,'data','eeg','R1275D','behavioral','FR1','session_0','host_pc','20170531_170954','eeg_timeseries.h5')
        self.raw_dataroot = osp.join(root,'protocols','r1','subjects','R1275D','experiments','FR1','sessions','0',
                                'ephys','current_processed','noreref','R1275D_FR1_0_31May17_2109')
        self.channels = channels
        self.h5file = h5py.File(self.h5_dataroot,'r')

    def tearDown(self):
        self.h5file.close()

    def test_h5reader_one_offset(self):
        channels=self.channels
        h5_data,_ = H5RawReader.read_h5file(self.h5file, channels, [0], 1000)

        raw_timeseries,_ = BaseRawReader(dataroot=self.raw_dataroot,channels=channels,start_offsets=np.array([0]),read_size=1000).read()
        assert (raw_timeseries.data == h5_data*raw_timeseries.gain).all()

    def test_h5reader_many_offsets(self):
        offsets = np.arange(0,210000,3000)
        h5_data,_ = H5RawReader.read_h5file(self.h5file, self.channels, offsets, 1000)
        raw_timeseries,_ = BaseRawReader(dataroot=self.raw_dataroot,channels=self.channels,start_offsets=offsets,read_size=1000).read()
        assert (raw_timeseries.data==h5_data*raw_timeseries.gain).all()

    def test_h5reader_out_of_bounds(self):
        offsets = np.arange(1000000,4000000,1000000)
        h5_data,h5_mask = H5RawReader.read_h5file(self.h5file, self.channels, offsets, 1000)
        raw_data,raw_mask = BaseRawReader(dataroot=self.raw_dataroot,channels=self.channels,start_offsets=offsets,read_size=1000).read()
        assert(raw_mask==h5_mask).all()
        assert(h5_data[h5_mask]==raw_data.data[raw_mask]).all()

    @pytest.mark.skip
    @pytest.mark.slow
    def test_h5_reader_timing(self):
        channels = np.array(['%.03d' % i for i in range(1, 100)])
        tic=time.time()
        h5_data,_ = H5RawReader.read_h5file(self.h5_dataroot, channels=channels)
        toc = time.time()
        del h5_data
        h5dur = toc-tic
        tic=time.time()
        raw_data,_ = BaseRawReader(dataroot=self.raw_dataroot,channels=channels).read()
        toc=time.time()
        del raw_data
        rawdur = toc-tic
        print('h5 file read in %s seconds'%h5dur)
        print('raw files read in %s seconds'%rawdur)
        assert h5dur<=rawdur


def test_h5reader_constructor():
    dataroot = osp.join(osp.dirname(__file__),
                        'data','R1308T','experiments','FR1','sessions','3','ephys','current_processed','noreref',
                        'R1308T_FR1_3_13Jun17_1917.h5')
    reader = H5RawReader(dataroot=dataroot,channels= channels)
    reader.read()
    assert reader.channel_name=='bipolar_pairs'

def test_with_events():
    dataroot_format = osp.join(osp.dirname(__file__),
                               'data','R1308T','experiments','FR1','sessions','%s','behavioral','current_processed',
                               'task_events.json')

    events = np.concatenate([CMLEventReader(filename=dataroot_format%s).read() for s in [1,2,3]]).view(np.recarray)
    events = events[(events.list==1) & (events.type=='WORD')]
    EEGReader(events=events,channels=channels,start_time=0.0,end_time=0.5).read()


