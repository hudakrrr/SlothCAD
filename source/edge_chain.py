"""Tangent-continuous edge chains, like Fusion's "Tangent Chain" edge selection.

Filleting one edge of a rounded outline (a line flowing smoothly into an arc)
usually fails or leaves a step, because the kernel cannot stop a rounded face at
a tangent joint. Selecting the whole smooth chain avoids that, and is what users
expect from a single click.
"""
import math
import numpy as np


def _key(point):return tuple(round(float(v),5) for v in point)


def _unit(vector):
    vector=np.asarray(vector,dtype=float);length=float(np.linalg.norm(vector))
    return vector/length if length>1e-12 else None


def end_directions(edges):
    """For every edge: [(vertex key, unit direction leaving that vertex along the edge), ...]."""
    result=[]
    for edge in edges:
        try:
            start=edge.startPoint().toTuple();end=edge.endPoint().toTuple()
            leaving_start=_unit(edge.tangentAt(0).toTuple());leaving_end=_unit(-np.asarray(edge.tangentAt(1).toTuple()))
        except Exception:
            result.append([]);continue
        ends=[]
        if leaving_start is not None:ends.append((_key(start),leaving_start))
        if leaving_end is not None:ends.append((_key(end),leaving_end))
        result.append(ends)
    return result


def tangent_chain(directions,seed,tolerance_degrees=2.):
    """Indices of all edges reachable from ``seed`` through smooth (G1) joints."""
    if not 0<=seed<len(directions):return []
    limit=-math.cos(math.radians(tolerance_degrees))
    at_vertex={}
    for index,ends in enumerate(directions):
        for key,direction in ends:at_vertex.setdefault(key,[]).append((index,direction))
    chain={seed};pending=[seed]
    while pending:
        current=pending.pop()
        for key,direction in directions[current]:
            for other,other_direction in at_vertex.get(key,[]):
                # Smooth continuation: the two edges leave the shared vertex in opposite directions.
                if other not in chain and float(direction@other_direction)<=limit:
                    chain.add(other);pending.append(other)
    return sorted(chain)
