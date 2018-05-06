# -*- coding: utf-8 -*-
#
from __future__ import print_function

from dolfin import (
    Mesh, MeshEditor, FunctionSpace, Expression, assemble, dx
    )
import numpy
import scipy.optimize
import voropy
from voropy.mesh_tri import MeshTri


from .helpers import (
    gather_stats, flip_until_delaunay, print_stats
    )


# [1] Long Chen, Michael Holst,
#     Efficient mesh optimization schemes based on Optimal Delaunay
#     Triangulations,
#     Comput. Methods Appl. Mech. Engrg. 200 (2011) 967–984,
#     <https://doi.org/10.1016/j.cma.2010.11.007>.


def odt(X, cells, verbose=True, tol=1.0e-5):
    '''Perform k steps of Laplacian smoothing to the mesh, i.e., moving each
    interior vertex to the arithmetic average of its neighboring points.
    '''
    # flat mesh
    assert numpy.all(abs(X[:, 2]) < 1.0e-15)

    mesh = MeshTri(X, cells, flat_cell_correction=None)
    initial_stats = gather_stats(mesh)

    mesh.mark_boundary()

    is_interior_node = numpy.logical_not(mesh.is_boundary_node)

    # flat triangles
    gdim = 2

    def f(x):
        interior_coords = x.reshape(-1, 2)
        interior_coords = numpy.column_stack([
            interior_coords, numpy.zeros(len(interior_coords))
            ])
        coords = X.copy()
        coords[is_interior_node] = interior_coords

        voropy_mesh = MeshTri(coords, cells, flat_cell_correction=None)
        # voropy_mesh.show()
        voropy_mesh, _ = flip_until_delaunay(voropy_mesh)

        # if verbose:
        #     print('\nstep: {}'.format(k))
        #     print_stats([gather_stats(voropy_mesh)])

        # create dolfin mesh
        editor = MeshEditor()
        dolfin_mesh = Mesh()
        # topological and geometrical dimension 2
        editor.open(dolfin_mesh, 'triangle', 2, 2, 1)
        editor.init_vertices(len(voropy_mesh.node_coords))
        editor.init_cells(len(cells))
        for k, point in enumerate(voropy_mesh.node_coords):
            editor.add_vertex(k, point[:2])
        for k, cell in enumerate(voropy_mesh.cells['nodes'].astype(numpy.uintp)):
            editor.add_cell(k, cell)
        editor.close()

        V = FunctionSpace(dolfin_mesh, 'CG', 1)
        q = Expression('x[0]*x[0] + x[1]*x[1]', element=V.ufl_element())
        out = assemble(q * dx(dolfin_mesh))
        # print(out)
        return out

    def jac(x):
        interior_coords = x.reshape(-1, 2)
        interior_coords = numpy.column_stack([
            interior_coords, numpy.zeros(len(interior_coords))
            ])
        coords = X.copy()
        coords[is_interior_node] = interior_coords

        voropy_mesh = MeshTri(coords, cells, flat_cell_correction=None)
        voropy_mesh, _ = flip_until_delaunay(voropy_mesh)

        grad = numpy.zeros(coords.shape)
        z = zip(
            voropy_mesh.cells['nodes'],
            voropy_mesh.get_cell_circumcenters(),
            voropy_mesh.cell_volumes
            )
        for cell, cc, vol in z:
            grad[cell] += (coords[cell] - cc) * vol
        grad *= 2 / (gdim+1)

        return grad[is_interior_node, :2].flatten()

    # TODO exact Hessian
    # The article [1] gives partial_ii correctly.
    # def get_hessian(x):
    #     interior_coords = x.reshape(-1, 2)
    #     interior_coords = numpy.column_stack([
    #         interior_coords, numpy.zeros(len(interior_coords))
    #         ])
    #     coords = X.copy()
    #     coords[is_interior_node] = interior_coords

    #     voropy_mesh = MeshTri(coords, cells, flat_cell_correction=None)
    #     voropy_mesh, _ = flip_until_delaunay(voropy_mesh)

    #     # Create Hessian
    #     I = []
    #     J = []
    #     V = []
    #     for cell, vol in zip(voropy_mesh.cells['nodes'], voropy_mesh.cell_volumes):
    #         idx = numpy.array(list(itertools.product(cell, repeat=2)))
    #         I.extend(idx[:, 0])
    #         J.extend(idx[:, 1])
    #         V += len(idx) * [vol]
    #     I = numpy.array(I)
    #     J = numpy.array(J)
    #     V = numpy.array(V)

    #     V *= 2 / (gdim+1)

    #     n = len(voropy_mesh.node_coords)
    #     matrix = sparse.coo_matrix((V, (I, J)),shape=(n, n)).tolil()

    #     # remove boundary rows and columns
    #     matrix = matrix[is_interior_node, :]
    #     matrix = matrix[:, is_interior_node]
    #     return matrix.tocsr()

    # def newton_direction(x, grad):
    #     hess = get_hessian(x)

    #     import betterspy
    #     betterspy.show(hess)
    #     # print(numpy.sort(numpy.linalg.eigvalsh(hess.toarray())))

    #     return -scipy.sparse.linalg.spsolve(hess, grad)

    x0 = X[is_interior_node, :2].flatten()

    # eps = 1.0e-10
    # M = []
    # for k in range(len(x0)):
    #     p = numpy.zeros(x0.shape)
    #     p[k] = 1.0
    #     M.append((jac(x0 + eps*p) - jac(x0 - eps*p)) / (2*eps))
    # M = numpy.column_stack(M)
    # print(M)
    # print()
    # import betterspy
    # betterspy.show(sparse.lil_matrix(M), colormap='viridis')
    # hess = get_hessian(x0)
    # print(hess)
    # betterspy.show(hess)
    # exit(1)

    out = scipy.optimize.minimize(
        f, x0,
        jac=jac,
        method='CG',
        tol=tol
        )
    # out = optipy.minimize(
    #     f, x0,
    #     jac=jac,
    #     get_search_direction=newton_direction,
    #     tol=tol
    #     )
    assert out.success, out.message

    interior_coords = out.x.reshape(-1, 2)
    interior_coords = numpy.column_stack([
        interior_coords, numpy.zeros(len(interior_coords))
        ])
    coords = X.copy()
    coords[is_interior_node] = interior_coords

    mesh = MeshTri(coords, cells, flat_cell_correction=None)
    mesh, _ = flip_until_delaunay(mesh)

    if verbose:
        print('\nBefore:' + 35*' ' + 'After:')
        print_stats([
            initial_stats,
            gather_stats(mesh),
            ])

    return mesh.node_coords, mesh.cells['nodes']


def odt_chen(X, cells, verbose=True, tol=1.0e-3):
    '''From

    Long Chen, Michael Holst,
    Efficient mesh optimization schemes based on Optimal Delaunay
    Triangulations,
    Comput. Methods Appl. Mech. Engrg. 200 (2011) 967–984,
    https://doi.org/10.1016/j.cma.2010.11.007.

    Idea: Move interior mesh points into the weighted circumcenters of their
    adjacent cells. If a triangle gets negative signed volume, don't move quite
    so far.
    '''
    # flat mesh
    assert numpy.all(abs(X[:, 2]) < 1.0e-15)
    X = X[:, :2]

    mesh = MeshTri(X, cells, flat_cell_correction=None)
    mesh, _ = flip_until_delaunay(mesh)
    original_orient = voropy.get_signed_tri_areas(
        mesh.cells['nodes'], mesh.node_coords
        ) > 0.0

    # mesh.save_png('step{:03d}'.format(0), show_centroids=False, show_coedges=False)

    initial_stats = gather_stats(mesh)

    mesh.mark_boundary()

    is_interior_node = numpy.logical_not(mesh.is_boundary_node)

    # flat triangles
    gdim = 2

    k = 0
    while True:
        k += 1
        weighted_cc_average = numpy.zeros(mesh.node_coords.shape)
        cc = mesh.get_cell_circumcenters()
        scaled_cc = (cc.T * mesh.cell_volumes).T
        numpy.add.at(weighted_cc_average, mesh.cells['nodes'][:, 0], scaled_cc)
        numpy.add.at(weighted_cc_average, mesh.cells['nodes'][:, 1], scaled_cc)
        numpy.add.at(weighted_cc_average, mesh.cells['nodes'][:, 2], scaled_cc)

        omega = numpy.zeros(len(mesh.node_coords))
        numpy.add.at(omega, mesh.cells['nodes'][:, 0], mesh.cell_volumes)
        numpy.add.at(omega, mesh.cells['nodes'][:, 1], mesh.cell_volumes)
        numpy.add.at(omega, mesh.cells['nodes'][:, 2], mesh.cell_volumes)

        weighted_cc_average  = (weighted_cc_average.T / omega).T

        # Step unless the orientation of any cell changes.
        alpha = 1.0
        xnew = (1-alpha) * mesh.node_coords + alpha * weighted_cc_average
        # Preserve boundary nodes
        xnew[mesh.is_boundary_node] = mesh.node_coords[mesh.is_boundary_node]
        new_orient = voropy.get_signed_tri_areas(
            mesh.cells['nodes'], xnew
            ) > 0.0
        while numpy.any(numpy.logical_xor(original_orient, new_orient)):
            alpha /= 2
            xnew = (1-alpha) * mesh.node_coords + alpha * weighted_cc_average
            xnew[mesh.is_boundary_node] = \
                mesh.node_coords[mesh.is_boundary_node]
            new_orient = voropy.get_signed_tri_areas(cells, xnew) > 0.0

        # Abort the loop if the update is small
        diff = xnew - mesh.node_coords
        print(k, alpha, numpy.sqrt(numpy.max(numpy.einsum('ij,ij->i', diff, diff))))
        if numpy.all(numpy.einsum('ij,ij->i', diff, diff) < tol**2):
            break

        mesh = MeshTri(xnew, mesh.cells['nodes'], flat_cell_correction=None)
        mesh, _ = flip_until_delaunay(mesh)
        mesh.mark_boundary()
        original_orient = voropy.get_signed_tri_areas(
            mesh.cells['nodes'], mesh.node_coords
            ) > 0.0

        # mesh.save_png('step{:03d}'.format(k), show_centroids=False, show_coedges=False)


    if verbose:
        print('\nBefore:' + 35*' ' + 'After ({} steps):'.format(k))
        print_stats([
            initial_stats,
            gather_stats(mesh),
            ])

    return mesh.node_coords, mesh.cells['nodes']
