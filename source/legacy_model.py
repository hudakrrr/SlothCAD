"""Version 1 primitive-profile compatibility and common numeric validation."""
from __future__ import annotations
import copy
import json
import math
import os
from pathlib import Path
import tempfile
import cadquery as cq

SCHEMA = 1

class ModelError(ValueError):
    pass

def positive(value, name):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ModelError(f'{name} must be a finite positive number.')
    return value

def number(value, name):
    value = float(value)
    if not math.isfinite(value):
        raise ModelError(f'{name} must be finite.')
    return value

def new_feature(kind='extrude'):
    if kind in ('fillet', 'chamfer'):
        return dict(kind=kind, name=kind.title(), enabled=True, radius=1., edges='vertical')
    return dict(kind='extrude', name='Extrude', enabled=True, profile='rectangle',
                plane='XY', operation='add', x=0., y=0., z=0., width=40., height=30.,
                radius=10., depth=10., points=[[-20.,-15.],[20.,-15.],[0.,15.]])

def profile_solid(f):
    plane = f.get('plane', 'XY')
    if plane not in ('XY','XZ','YZ'):
        raise ModelError('Choose XY, XZ, or YZ.')
    x,y,z = (number(f.get(k,0), k) for k in ('x','y','z'))
    w = cq.Workplane(plane, origin=(x,y,z))
    profile = f.get('profile')
    if profile == 'rectangle':
        w = w.rect(positive(f['width'],'Width'), positive(f['height'],'Height'))
    elif profile == 'circle':
        w = w.circle(positive(f['radius'],'Radius'))
    elif profile == 'polygon':
        points = [(number(p[0],'Point X'), number(p[1],'Point Y')) for p in f['points']]
        if len(points) < 3 or len(set(points)) != len(points):
            raise ModelError('A polygon needs at least three distinct vertices.')
        w = w.polyline(points).close()
    else:
        raise ModelError('Unknown sketch profile.')
    depth = number(f['depth'],'Extrusion depth')
    if depth == 0:
        raise ModelError('Extrusion depth cannot be zero.')
    return w.extrude(depth)

