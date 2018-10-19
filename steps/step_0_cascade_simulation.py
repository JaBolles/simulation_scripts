#!/bin/sh /cvmfs/icecube.opensciencegrid.org/py2-v3.0.1/icetray-start
#METAPROJECT simulation/V06-00-03
from __future__ import division
import click
import yaml
import copy

import numpy as np
from scipy.spatial import ConvexHull

from icecube.simprod import segments

from I3Tray import I3Tray, I3Units
from icecube import icetray, dataclasses

from utils import create_random_services, get_run_folder


class CascadeFactory(icetray.I3ConditionalModule):
    def __init__(self, context):
        """Class to create and inject Cascades.

        Parameters
        ----------
        context : TYPE
            Description
        """
        icetray.I3ConditionalModule.__init__(self, context)
        self.AddOutBox('OutBox')
        self.AddParameter('azimuth_range',
                          '[min, max] of primary azimuth in degree.', [0, 360])
        self.AddParameter('zenith_range',
                          '[min, max] of primary zenith in degree.', [0, 180])
        self.AddParameter('hadron_energy_range', '', [10000, 10000])
        self.AddParameter('fractional_energy_in_hadrons_range',
                          'Fraction of primary energy in hadrons', [0, 1.])
        self.AddParameter('time_range', '[min, max] of vertex time in ns.',
                          [9000, 12000])
        self.AddParameter('x_range',
                          '[min, max] of vertex x-coordinate in meters.',
                          [-500, 500])
        self.AddParameter('y_range',
                          '[min, max] of vertex y-coordinate in meters.',
                          [-500, 500])
        self.AddParameter('z_range',
                          '[min, max] of vertex z-coordinate in meters.',
                          [-500, 500])
        self.AddParameter('flavors',
                          'List of neutrino flavors to simulate.',
                          ['NuE', 'NuMu', 'NuTau'])
        self.AddParameter('interaction_types',
                          'List of interaction types to simulate: CC or NC',
                          ['CC', 'NC'])
        self.AddParameter('random_state', '', 1337)
        self.AddParameter('random_service', '', None)
        self.AddParameter('num_events', '', 1)

    def Configure(self):
        """Configures CascadeFactory.

        Raises
        ------
        ValueError
            If interaction type or flavor is unkown.
        """
        self.azimuth_range = self.GetParameter('azimuth_range')
        self.zenith_range = self.GetParameter('zenith_range')
        self.hadron_energy_range = self.GetParameter('hadron_energy_range')
        self.fractional_energy_in_hadrons_range = self.GetParameter(
                                        'fractional_energy_in_hadrons_range')
        self.time_range = self.GetParameter('time_range')
        self.x_range = self.GetParameter('x_range')
        self.y_range = self.GetParameter('y_range')
        self.z_range = self.GetParameter('z_range')
        self.flavors = self.GetParameter('flavors')
        self.num_flavors = len(self.flavors)
        self.interaction_types = self.GetParameter('interaction_types')
        self.num_interaction_types = len(self.interaction_types)
        self.random_state = self.GetParameter('random_state')
        self.random_service = self.GetParameter('random_service')
        if not isinstance(self.random_state, np.random.RandomState):
            self.random_state = np.random.RandomState(self.random_state)
        self.num_events = self.GetParameter('num_events')
        self.events_done = 0
        self.eps = 1e-6

        # make lowercase
        self.flavors = [f.lower() for f in self.flavors]
        self.interaction_types = [i.lower() for i in self.interaction_types]

        # --------------
        # sanity checks:
        # --------------
        for int_type in self.interaction_types:
            if int_type not in ['cc', 'nc']:
                raise ValueError('Interaction unkown: {!r}'.format(int_type))

        for flavor in self.flavors:
            if flavor not in ['nue', 'numu', 'nutau']:
                raise ValueError('Flavor unkown: {!r}'.format(flavor))
        # --------------

    def DAQ(self, frame):
        """Inject casacdes into I3MCtree.

        Parameters
        ----------
        frame : icetray.I3Frame.DAQ
            An I3 q-frame.

        Raises
        ------
        ValueError
            If interaction type is unknown.
        """
        # --------------
        # sample cascade
        # --------------
        # vertex
        vertex_x = self.random_service.uniform(*self.x_range) * I3Units.m
        vertex_y = self.random_service.uniform(*self.y_range) * I3Units.m
        vertex_z = self.random_service.uniform(*self.z_range) * I3Units.m
        vertex = dataclasses.I3Position(
                        vertex_x * I3Units.m,
                        vertex_y * I3Units.m,
                        vertex_z * I3Units.m)

        vertex_time = self.random_service.uniform(*self.time_range)*I3Units.ns

        # direction
        azimuth = self.random_service.uniform(*self.azimuth_range)*I3Units.deg
        zenith = self.random_service.uniform(*self.zenith_range)*I3Units.deg

        # energy
        hadron_energy = self.random_service.uniform(
                                    *self.hadron_energy_range) * I3Units.GeV
        fraction = self.random_service.uniform(
                                    *self.fractional_energy_in_hadrons_range)
        primary_energy = hadron_energy / (self.eps + fraction)
        daughter_energy = primary_energy - hadron_energy

        # flavor and interaction
        flavor = self.flavors[self.random_service.integer(self.num_flavors)]
        interaction_type = self.interaction_types[
                    self.random_service.integer(self.num_interaction_types)]

        # create particle
        primary = dataclasses.I3Particle()
        daughter = dataclasses.I3Particle()

        primary.time = vertex_time * I3Units.ns
        primary.dir = dataclasses.I3Direction(zenith, azimuth)
        primary.energy = primary_energy * I3Units.GeV
        primary.pos = vertex
        primary.speed = dataclasses.I3Constants.c
        # Assume the vertex position in range is in ice, so the primary is the
        # in ice neutrino that interacts
        primary.location_type = dataclasses.I3Particle.LocationType.InIce
        daughter.location_type = dataclasses.I3Particle.LocationType.InIce

        daughter.time = primary.time
        daughter.dir = primary.dir
        daughter.speed = primary.speed
        daughter.pos = primary.pos
        daughter.energy = daughter_energy * I3Units.GeV

        if interaction_type == 'cc' and flavor == 'numu':
            daughter.shape = dataclasses.I3Particle.InfiniteTrack
        else:
            daughter.shape = dataclasses.I3Particle.Cascade

        if flavor == 'numu':
            primary.type = dataclasses.I3Particle.ParticleType.NuMu
            if interaction_type == 'cc':
                daughter.type = dataclasses.I3Particle.ParticleType.MuMinus
            elif interaction_type == 'nc':
                daughter.type = dataclasses.I3Particle.ParticleType.NuMu
        elif flavor == 'nutau':
            primary.type = dataclasses.I3Particle.ParticleType.NuTau
            if interaction_type == 'cc':
                daughter.type = dataclasses.I3Particle.ParticleType.TauMinus
            elif interaction_type == 'nc':
                daughter.type = dataclasses.I3Particle.ParticleType.NuTau
        elif flavor == 'nue':
            primary.type = dataclasses.I3Particle.ParticleType.NuE
            if interaction_type == 'cc':
                daughter.type = dataclasses.I3Particle.ParticleType.EMinus
            elif interaction_type == 'nc':
                daughter.type = dataclasses.I3Particle.ParticleType.NuE
        else:
            raise ValueError(('particle_type {!r} not known or not ' +
                              'implemented'.format(self.particle_type)))

        # add hadrons
        hadrons = dataclasses.I3Particle()
        hadrons.energy = hadron_energy * I3Units.GeV
        hadrons.pos = daughter.pos
        hadrons.time = daughter.time
        hadrons.dir = daughter.dir
        hadrons.speed = daughter.speed
        hadrons.type = dataclasses.I3Particle.ParticleType.Hadrons
        hadrons.location_type = daughter.location_type
        hadrons.shape = dataclasses.I3Particle.Cascade

        # Fill primary and daughter particles into a MCTree
        mctree = dataclasses.I3MCTree()
        mctree.add_primary(primary)
        mctree.append_child(primary, daughter)
        mctree.append_child(primary, hadrons)

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
    click.echo('Azimuth: [{},{}]'.format(*cfg['azimuth_range']))
    click.echo('Zenith: [{},{}]'.format(*cfg['zenith_range']))
    click.echo('Energy: [{},{}]'.format(*cfg['hadron_energy_range']))
    click.echo('Vertex x: [{},{}]'.format(*cfg['x_range']))
    click.echo('Vertex y: [{},{}]'.format(*cfg['y_range']))
    click.echo('Vertex z: [{},{}]'.format(*cfg['z_range']))

    # crate random services
    random_services, _ = create_random_services(
        dataset_number=cfg['dataset_number'],
        run_number=cfg['run_number'],
        seed=cfg['seed'],
        n_services=2)

    # --------------------------------------
    # Build IceTray
    # --------------------------------------
    tray = I3Tray()
    tray.AddModule('I3InfiniteSource', 'source',
                   # Prefix=gcdfile,
                   Stream=icetray.I3Frame.DAQ)

    tray.AddModule(CascadeFactory,
                   'make_cascades',
                   azimuth_range=cfg['azimuth_range'],
                   zenith_range=cfg['zenith_range'],
                   hadron_energy_range=cfg['hadron_energy_range'],
                   fractional_energy_in_hadrons_range=cfg[
                                        'fractional_energy_in_hadrons_range'],
                   time_range=cfg['time_range'],
                   x_range=cfg['x_range'],
                   y_range=cfg['y_range'],
                   z_range=cfg['z_range'],
                   flavors=cfg['flavors'],
                   interaction_types=cfg['interaction_types'],
                   num_events=cfg['n_events_per_run'],
                   random_state=cfg['seed'],
                   random_service=random_services[0])

    tray.AddSegment(segments.PropagateMuons,
                    'propagate_muons',
                    RandomService=random_services[1],
                    **cfg['muon_propagation_config'])

    # --------------------------------------
    # Distance Splits
    # --------------------------------------
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
    # --------------------------------------

    click.echo('Scratch: {}'.format(scratch))
    tray.AddModule("TrashCan", "the can")
    tray.Execute()
    tray.Finish()


if __name__ == '__main__':
    main()
