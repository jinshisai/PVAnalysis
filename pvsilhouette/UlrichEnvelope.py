import numpy as np
import matplotlib.pyplot as plt
from astropy import constants, units

au = units.au.to('m')
GG = constants.G.si.value
M_sun = constants.M_sun.si.value
deg = units.deg.to('radian')


def velrho(radius, theta):
    radius = radius.clip(1e-10, None)
    parity = np.sign(mu := np.cos(theta))
    mu = np.abs(mu).clip(1e-10, 1)
    p = (radius - 1) / 3.
    q = mu * radius / 2.
    mu0 = np.full_like(radius, np.nan)
    ### three cases for computational stability
    # r >= 1 (p >= 0, D >= 0)
    c = (radius >= 1)
    D = q[c]**2 + p[c]**3
    qD = q[c] * (D)**(-1/2)
    mu0[c] = D**(1/6) * ((1 + qD)**(1/3) - (1 - qD)**(1/3))
    # r < 1 (p < 0) and D >= 0
    p_minus = (-p).clip(0, None)
    D = q**2 - p_minus**3
    c = (radius < 1) * (D >= 0)
    mu0[c] = (q[c] + np.sqrt(D[c]))**(1/3) + (q[c] - np.sqrt(D[c]))**(1/3)
    # D < 0 (p < 0, r < 1)
    c = (D < 0)
    mu0[c] = 2 * np.sqrt(p_minus[c]) \
             * np.cos(np.arccos(q[c] * p_minus[c]**(-3/2)) / 3.)
    
    mm = mu / mu0
    vr = -np.sqrt(1 + mm) / np.sqrt(radius)
    vt = parity * np.sqrt(1 + mm) * (mu0 - mu) / np.sin(theta) / np.sqrt(radius)
    vp = np.sqrt(1 - mm) / np.sqrt(radius)
    rho = radius**(-3/2) / np.sqrt(1 + mm) / (2 / radius * mu0**2 + mm)
    return vr, vt, vp, rho

def kepvel(radius, theta):
    r = radius.clip(1e-10, None) * np.sin(theta)
    vr = np.zeros_like(r)
    vt = np.zeros_like(r)
    vp = 1 / np.sqrt(r)
    return vr, vt, vp

def xyz2rtp(x, y, z):
    r = np.sqrt(x**2 + y**2 + z**2).clip(1e-10, None)
    t = np.arccos(z / r)
    p = np.arctan2(x, -y)
    return r, t, p

def rotbase(t, p):
    """t is an inclination angle from +z to (x, y)=(sin p, -cos p).
       p is an azimuthal angle from -y to +x.
    """
    er = np.array([np.sin(t) * np.sin(p), -np.sin(t) * np.cos(p), np.cos(t)])
    et = np.array([np.cos(t) * np.sin(p), -np.cos(t) * np.cos(p), -np.sin(t)])
    ep = np.array([np.cos(p), np.sin(p), np.zeros_like(p)])
    return er, et, ep

def XYZ2xyz(incl, phi, X, Y, Z):
    """The observer coordinate (X,Y,Z) and the envelope coordinate (x,y,z)
       are linked as X * ep + Y * (-et) + Z * er = x, y, z.
    """
    shape = np.shape(X)
    er, et, ep = rotbase(incl, phi)
    x, y, z = np.outer(ep, X.ravel()) \
              + np.outer(-et, Y.ravel()) \
              + np.outer(er, Z.ravel())
    x = np.reshape(x, shape)
    y = np.reshape(y, shape)
    z = np.reshape(z, shape)
    #r2D = np.sqrt(x**2 + y**2)
    #x[r2D < 1] = np.nan
    #y[r2D < 1] = np.nan
    #z[r2D < 1] = np.nan
    return x, y, z

def losvel(elos, r, t, p, kepler=False):
    """Line-of-sight velocity with a given vector, elos,
       which points to the observer in the envelople coordinate.
    """
    shape = np.shape(r)
    if kepler:
        vr, vt, vp = kepvel(r.ravel(), t.ravel())
    else:
        vr, vt, vp, _ = velrho(r.ravel(), t.ravel())
    er, et, ep = rotbase(t.ravel(), p.ravel())
    e = np.moveaxis(np.full((len(r.ravel()), 3), elos), -1, 0)
    vlos = -vr * np.sum(er * e, axis=0) \
           -vt * np.sum(et * e, axis=0) \
           -vp * np.sum(ep * e, axis=0)
    return np.reshape(vlos, shape)

def velmax(r: np.ndarray, Mstar: float, Rc: float, incl: float):
    irad = np.radians(incl)
    vunit = np.sqrt(GG * Mstar * M_sun / Rc / au) * 1e-3
    X = r / Rc
    Z = r / Rc
    X, Z = np.meshgrid(X, Z)  # X is inner, second axis
    Y = np.zeros_like(X)
    R = np.hypot(X, Z)
    X[R < 1] = np.nan
    Y[R < 1] = np.nan
    Z[R < 1] = np.nan
    elos = [0, -np.sin(irad), np.cos(irad)]
    a = {}
    vlos = losvel(elos, *xyz2rtp(*XYZ2xyz(irad, 0, X, Y, Z))) * vunit
    vlosmax = np.nanmax(vlos, axis=0)
    vlosmin = np.nanmin(vlos, axis=0)
    a['major'] = {'vlosmax':vlosmax, 'vlosmin':vlosmin}
    vlos = losvel(elos, *xyz2rtp(*XYZ2xyz(irad, 0, Y, X, Z))) * vunit
    vlosmax = np.nanmax(vlos, axis=0)
    vlosmin = np.nanmin(vlos, axis=0)
    a['minor'] = {'vlosmax':vlosmax, 'vlosmin':vlosmin}
    return a