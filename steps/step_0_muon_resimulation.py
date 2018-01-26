#!/bin/sh /cvmfs/icecube.opensciencegrid.org/py2-v2/icetray-start
#METAPROJECT /home/mmeier/combo_test/build
# use self-build combo until the I3CrossSection pybindings are included
# in a release
from __future__ import division
import click
import yaml
import copy

import numpy as np

from icecube.simprod import segments

from I3Tray import I3Tray, I3Units
from icecube import icetray, dataclasses

from utils import create_random_services, get_run_folder


def create_muon(
            azimuth_range=[0,360],
            zenith_range=[0,180],
            energy_range=[10000,10000],
            anchor_time_range=[9000,12000],
            anchor_x_range=[-400,400],
            anchor_y_range=[-400,400],
            anchor_z_range=[-400,400],
            length_to_go_back=2000,
            random_service=None,
            ):
    '''
    Generates muon where energy, direction and position is 
    uniformly sampled within given range.

    First samples direction and anchor point. Then calculates
    the vertex by going back along the track from the anchor 
    point.

    azimuth_range: [min, max] 
                   in degree

    zenith_range: [min, max] 
                   in degree

    energy_range: [min, max] 
                   in GeV

    anchor_time_range: [min, max] 
                   in ns
                Approximate time when
                muon is in detector at
                the simulated anchor
                point

    anchor_i_range: [min, max]
                    in m
                The anchor point coordinate i

    length_to_go_back: float
                Length to go back along track from 
                anchor point, e.g. how far away
                to set the vertex of the point

    seed: random seed
    '''

    #------
    # sample direction and energy
    #------
    azimuth = random_service.uniform(*azimuth_range) * I3Units.deg
    zenith = random_service.uniform(*zenith_range) * I3Units.deg
    energy = random_service.uniform(*energy_range) * I3Units.GeV

    # create particle
    muon = dataclasses.I3Particle()
    muon.speed = dataclasses.I3Constants.c
    muon.location_type = dataclasses.I3Particle.LocationType.InIce
    muon.type = dataclasses.I3Particle.ParticleType.MuMinus
    muon.dir = dataclasses.I3Direction(zenith,azimuth)
    muon.energy = energy * I3Units.GeV

    #------
    # get anchor point and time in detector
    #------
    anchor_x = random_service.uniform(*anchor_x_range)
    anchor_y = random_service.uniform(*anchor_y_range)
    anchor_z = random_service.uniform(*anchor_z_range)

    anchor = dataclasses.I3Position(
                    anchor_x * I3Units.m,
                    anchor_y * I3Units.m,
                    anchor_z * I3Units.m)

    anchor_time = random_service.uniform(*anchor_time_range) * I3Units.ns

    #------
    # calculate vertex
    #------
    vertex = anchor - length_to_go_back*I3Units.m * muon.dir
    travel_time = length_to_go_back * I3Units.m / muon.speed
    vertex_time = anchor_time - travel_time * I3Units.ns

    
    muon.pos = vertex
    muon.time = vertex_time * I3Units.ns

    return muon




class ParticleMultiplier(icetray.I3ConditionalModule):
    def __init__(self, context):
        icetray.I3ConditionalModule.__init__(self, context)
        self.AddParameter('num_events', '', None)
        self.AddParameter('primary', '', None)

    def Configure(self):
        self.num_events = self.GetParameter('num_events')
        self.primary = self.GetParameter('primary')
        
        self.events_done = 0


    def DAQ(self, frame):

        # Fill primary into an MCTree
        mctree = dataclasses.I3MCTree()
        mctree.add_primary(self.primary)

        frame["I3MCTree_preMuonProp"] = mctree
        self.PushFrame(frame)

        self.events_done += 1
        if self.events_done >= self.num_events:
            self.RequestSuspension()




@click.command()
@click.argument('cfg', click.Path(exists=True))
@click.argument('run_number', type=int)
@click.option('--scratch/--no-scratch', default=True)
def main(cfg, run_number, scratch):
    with open(cfg, 'r') as stream:
        cfg = yaml.load(stream)
    cfg['run_number'] = run_number
    cfg['run_folder'] = get_run_folder(run_number)
    if scratch:
        outfile = cfg['scratchfile_pattern'].format(**cfg)
    else:
        outfile = cfg['outfile_pattern'].format(**cfg)
    outfile = outfile.replace(' ', '0')

    click.echo('Run: {}'.format(run_number))
    click.echo('Outfile: {}'.format(outfile))
    click.echo('Azimuth: [{},{}]'.format(cfg['azimuth_min'],
                                         cfg['azimuth_max']))
    click.echo('Zenith: [{},{}]'.format(cfg['zenith_min'],
                                        cfg['zenith_max']))
    click.echo('Energy: [{},{}]'.format(cfg['e_min'],
                                         cfg['e_max']))

    # crate random services
    random_services, _ = create_random_services(
        dataset_number=cfg['dataset_number'],
        run_number=cfg['run_number'],
        seed=cfg['seed'],
        n_services=2)

    # create muon
    muon = create_muon(
            azimuth_range=[cfg['azimuth_min'],cfg['azimuth_max']],
            zenith_range=[cfg['zenith_min'],cfg['zenith_max']],
            energy_range=[cfg['e_min'],cfg['e_max']],
            anchor_time_range=cfg['anchor_time_range'],
            anchor_x_range=cfg['anchor_x_range'],
            anchor_y_range=cfg['anchor_y_range'],
            anchor_z_range=cfg['anchor_z_range'],
            length_to_go_back=cfg['length_to_go_back'],
            random_service=random_services[0],
            )


    #--------------------------------------
    # Build IceTray
    #--------------------------------------
    tray = I3Tray()
    tray.AddModule('I3InfiniteSource', 'source',
                   # Prefix=gcdfile,
                   Stream=icetray.I3Frame.DAQ)

    tray.AddModule(ParticleMultiplier,
                   'make_particles',
                   num_events=cfg['n_events_per_run'],
                   primary= muon)

    tray.AddSegment(segments.PropagateMuons,
                    'propagate_muons',
                    RandomService=random_services[1],
                    **cfg['muon_propagation_config'])


    #--------------------------------------
    # Distance Splits
    #--------------------------------------
    if cfg['distance_splits'] is not None:
        click.echo('SplittingDistance: {}'.format(
            cfg['distance_splits']))
        distance_splits = np.atleast_1d(cfg['distance_splits'])
        dom_limits = np.atleast_1d(cfg['threshold_doms'])
        if len(dom_limits) == 1:
            dom_limits = np.ones_like(distance_splits) * cfg['threshold_doms']
        oversize_factors = np.atleast_1d(cfg['oversize_factors'])
        order = np.argsort(distance_splits)

        distance_splits = distance_splits[order]
        dom_limits = dom_limits[order]
        oversize_factors = oversize_factors[order]

        stream_objects = generate_stream_object(distance_splits,
                                                dom_limits,
                                                oversize_factors)
        tray.AddModule(OversizeSplitterNSplits,
                       "OversizeSplitterNSplits",
                       thresholds=distance_splits,
                       thresholds_doms=dom_limits,
                       oversize_factors=oversize_factors)
        for stream_i in stream_objects:
            outfile_i = stream_i.transform_filepath(outfile)
            tray.AddModule("I3Writer",
                           "writer_{}".format(stream_i.stream_name),
                           Filename=outfile_i,
                           Streams=[icetray.I3Frame.DAQ,
                                    icetray.I3Frame.Physics,
                                    icetray.I3Frame.Stream('S'),
                                    icetray.I3Frame.Stream('M')],
                           If=stream_i)
            click.echo('Output ({}): {}'.format(stream_i.stream_name,
                                                outfile_i))
    else:
        click.echo('Output: {}'.format(outfile))
        tray.AddModule("I3Writer", "writer",
                       Filename=outfile,
                       Streams=[icetray.I3Frame.DAQ,
                                icetray.I3Frame.Physics,
                                icetray.I3Frame.Stream('S'),
                                icetray.I3Frame.Stream('M')])
    #--------------------------------------

    click.echo('Scratch: {}'.format(scratch))
    tray.AddModule("TrashCan", "the can")
    tray.Execute()
    tray.Finish()

if __name__ == '__main__':
    main()
