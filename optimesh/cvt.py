# -*- coding: utf-8 -*-
#
from __future__ import print_function

import numpy
import pyamg
import scipy.sparse
from meshplex import MeshTri

from .helpers import runner


def fixed_point_uniform(*args, **kwargs):
    """Lloyd's algorithm.
    """
    def get_new_points(mesh):
        return mesh.control_volume_centroids[mesh.is_interior_node]

    return runner(get_new_points, *args, **kwargs, flat_cell_correction="boundary")


def scaled_gradient_update(mesh):
    """Equivalent to Lloyd's algorithm.
    """
    # out = mesh.control_volume_centroids - mesh.node_coords
    out = -0.5 * (jac_uniform(mesh).reshape(-1, 2).T / mesh.control_volumes).T
    return out


def jac_uniform(mesh):
    # create Jacobian
    centroids = mesh.control_volume_centroids
    X = mesh.node_coords
    jac = 2 * ((X - centroids).T * mesh.control_volumes).T
    return jac.flatten()


def newton_update(mesh):
    X = mesh.node_coords
    cells = mesh.cells["nodes"]

    # TODO remove this assertion and test
    # flat mesh
    assert X.shape[1] == 2

    i_boundary = numpy.where(mesh.is_boundary_node)[0]

    # Finite difference Jacobian
    eps = 1.0e-5
    X_orig = mesh.node_coords.copy()
    cols = []
    for kk in range(X.shape[0]):
        for kxy in [0, 1]:
            X = X_orig.copy()
            X[kk, kxy] += eps
            jac_plus = jac_uniform(MeshTri(X, cells))
            #
            X = X_orig.copy()
            X[kk, kxy] -= eps
            jac_minus = jac_uniform(MeshTri(X, cells))
            #
            cols.append((jac_plus - jac_minus) / (2 * eps))
    matrix = numpy.column_stack(cols)

    print(numpy.max(numpy.abs(matrix - matrix.T)))

    # Apply Dirichlet conditions.
    for i in numpy.where(mesh.is_boundary_node)[0]:
        matrix[2 * i + 0] = 0.0
        matrix[2 * i + 1] = 0.0
        matrix[2 * i + 0, 2 * i + 0] = 1.0
        matrix[2 * i + 1, 2 * i + 1] = 1.0

    rhs = -jac_uniform(mesh)
    rhs[2 * i_boundary + 0] = 0.0
    rhs[2 * i_boundary + 1] = 0.0

    out = numpy.linalg.solve(matrix, rhs)
    return out.reshape(-1, 2)


def quasi_newton_update(mesh):
    X = mesh.node_coords

    # TODO remove this assertion and test
    # flat mesh
    assert X.shape[1] == 2

    i_boundary = numpy.where(mesh.is_boundary_node)[0]

    # create approximate Hessian
    row_idx = []
    col_idx = []
    vals = []
    for cell, ce_ratios, ei_outer_ei in zip(
        mesh.cells["nodes"], mesh.ce_ratios.T, numpy.moveaxis(mesh.ei_outer_ei, 0, 1)
    ):
        # m3 = -0.5 * (ce_ratios * ei_outer_ei.T).T
        for idx, ce in zip([[1, 2], [2, 0], [0, 1]], ce_ratios):
            i = [cell[idx[0]], cell[idx[1]]]
            ei = mesh.node_coords[i[1]] - mesh.node_coords[i[0]]
            ei_outer_ei = numpy.outer(ei, ei)
            m = -0.5 * ce * ei_outer_ei
            row_idx += [
                2 * i[0] + 0,
                2 * i[0] + 0,
                # 2 * i[0] + 0,
                # 2 * i[0] + 0,
                2 * i[0] + 1,
                2 * i[0] + 1,
                # 2 * i[0] + 1,
                # 2 * i[0] + 1,
                # 2 * i[1] + 0,
                # 2 * i[1] + 0,
                2 * i[1] + 0,
                2 * i[1] + 0,
                # 2 * i[1] + 1,
                # 2 * i[1] + 1,
                2 * i[1] + 1,
                2 * i[1] + 1,
            ]
            col_idx += [
                2 * i[0] + 0,
                2 * i[0] + 1,
                # 2 * i[1] + 0,
                # 2 * i[1] + 1,
                2 * i[0] + 0,
                2 * i[0] + 1,
                # 2 * i[1] + 0,
                # 2 * i[1] + 1,
                # 2 * i[0] + 0,
                # 2 * i[0] + 1,
                2 * i[1] + 0,
                2 * i[1] + 1,
                # 2 * i[0] + 0,
                # 2 * i[0] + 1,
                2 * i[1] + 0,
                2 * i[1] + 1,
            ]
            vals += [
                m[0, 0],
                m[0, 1],
                # m[0, 0],
                # m[0, 1],
                m[1, 0],
                m[1, 1],
                # m[1, 0],
                # m[1, 1],
                # m[0, 0],
                # m[0, 1],
                m[0, 0],
                m[0, 1],
                # m[1, 0],
                # m[1, 1],
                m[1, 0],
                m[1, 1],
            ]

    # add diagonal
    for k, control_volume in enumerate(mesh.control_volumes):
        row_idx += [2 * k, 2 * k + 1]
        col_idx += [2 * k, 2 * k + 1]
        vals += [2 * control_volume, 2 * control_volume]

    n = mesh.control_volumes.shape[0]
    matrix = scipy.sparse.coo_matrix((vals, (row_idx, col_idx)), shape=(2 * n, 2 * n))

    # print()
    # print(matrix.toarray()[:, k0].reshape(-1))
    # print()
    # print(matrix.toarray()[:, 2 * kk + kxy] - 2 * h55)
    # exit(1)

    # Transform to CSR format for efficiency
    matrix = matrix.tocsr()

    # print(numpy.sort(numpy.linalg.eigvals(matrix.toarray()))[:5])
    # exit(1)

    # Apply Dirichlet conditions.
    # Set all Dirichlet rows to 0.
    for i in numpy.where(mesh.is_boundary_node)[0]:
        matrix.data[matrix.indptr[2 * i + 0] : matrix.indptr[2 * i + 0 + 1]] = 0.0
        matrix.data[matrix.indptr[2 * i + 1] : matrix.indptr[2 * i + 1 + 1]] = 0.0
    # Set the diagonal and RHS.
    d = matrix.diagonal()
    d[2 * i_boundary + 0] = 1.0
    d[2 * i_boundary + 1] = 1.0
    matrix.setdiag(d)

    rhs = -jac_uniform(mesh)
    rhs[2 * i_boundary + 0] = 0.0
    rhs[2 * i_boundary + 1] = 0.0

    # print("ok hi")
    # print(numpy.sort(numpy.linalg.eigvals(matrix.toarray())))
    # exit(1)

    out = scipy.sparse.linalg.spsolve(matrix, rhs)
    # ml = pyamg.ruge_stuben_solver(matrix)
    # out = ml.solve(rhs, tol=1.0e-10)

    return out.reshape(-1, 2)


def quasi_newton_uniform(*args, **kwargs):
    def get_new_points(mesh):
        # do one Newton step
        # TODO need copy?
        x = mesh.node_coords.copy()
        # x += scaled_gradient_update(mesh)
        # x += newton_update(mesh)
        x += quasi_newton_update(mesh)
        return x[mesh.is_interior_node]

    return runner(get_new_points, *args, **kwargs, flat_cell_correction="boundary")
