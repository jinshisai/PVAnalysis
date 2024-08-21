# -*- coding: utf-8 -*-
#----------------------------------------------------------------------------
# Created By  : Yusuke Aso
# Created Date: 2022 Jan 27
# Updated Date: 2023 Nov 21 by J.Sai
# version = alpha
# ---------------------------------------------------------------------------
"""
This script makes position-velocity diagrams along the major anc minor axes and reproduces their silhouette by the UCM envelope.
The main class PVSilhouette can be imported to do each steps separately.

Note. FITS files with multiple beams are not supported. The dynamic range for xlim_plot and vlim_plot should be >10 for nice tick labels.
"""

import numpy as np
import matplotlib.pyplot as plt
from astropy.io import fits
from astropy import constants
from astropy.coordinates import SkyCoord
from scipy.interpolate import RegularGridInterpolator as RGI
from tqdm import tqdm
import warnings

from utils import emcee_corner
from pvsilhouette.mockpvd import MockPVD

warnings.simplefilter('ignore', RuntimeWarning)


class PVSilhouette():

#    def __init__(self):

    def read_cubefits(self, cubefits: str, center: str = None,
                      dist: float = 1, vsys: float = 0,
                      xmax: float = 1e4, ymax: float = 1e4,
                      vmin: float = -100, vmax: float = 100,
                      sigma: float = None) -> dict:
        """
        Read a position-velocity diagram in the FITS format.

        Parameters
        ----------
        cubefits : str
            Name of the input FITS file including the extension.
        center : str
            Coordinates of the target: e.g., "01h23m45.6s 01d23m45.6s".
        dist : float
            Distance of the target, used to convert arcsec to au.
        vsys : float
            Systemic velocity of the target.
        xmax : float
            The R.A. axis is limited to (-xmax, xmax) in the unit of au.
        ymax : float
            The Dec. axis is limited to (-xmax, xmax) in the unit of au.
        vmax : float
            The velocity axis of the PV diagram is limited to (vmin, vmax).
        vmin : float
            The velocity axis of the PV diagram is limited to (vmin, vmax).
        sigma : float
            Standard deviation of the FITS data. None means automatic.

        Returns
        ----------
        fitsdata : dict
            x (1D array), v (1D array), data (2D array), header, and sigma.
        """
        cc = constants.c.si.value
        f = fits.open(cubefits)[0]
        d, h = np.squeeze(f.data), f.header
        if center is None:
            cx, cy = 0, 0
        else:
            coord = SkyCoord(center, frame='icrs')
            cx = coord.ra.degree - h['CRVAL1']
            cy = coord.dec.degree - h['CRVAL2']
        if sigma is None:
            sigma = np.mean([np.nanstd(d[:2]), np.std(d[-2:])])
            print(f'sigma = {sigma:.3e}')
        x = (np.arange(h['NAXIS1']) - h['CRPIX1'] + 1) * h['CDELT1']
        y = (np.arange(h['NAXIS2']) - h['CRPIX2'] + 1) * h['CDELT2']
        v = (np.arange(h['NAXIS3']) - h['CRPIX3'] + 1) * h['CDELT3']
        v = v + h['CRVAL3']
        x = (x - cx) * 3600. * dist  # au
        y = (y - cy) * 3600. * dist  # au
        v = (1. - v / h['RESTFRQ']) * cc / 1.e3 - vsys  # km/s
        i0, i1 = np.argmin(np.abs(x - xmax)), np.argmin(np.abs(x + xmax))
        j0, j1 = np.argmin(np.abs(y + ymax)), np.argmin(np.abs(y - ymax))
        k0, k1 = np.argmin(np.abs(v - vmin)), np.argmin(np.abs(v - vmax))
        self.offpix = (i0, j0, k0)
        x, y, v = x[i0:i1 + 1], y[j0:j1 + 1], v[k0:k1 + 1],
        d =  d[k0:k1 + 1, j0:j1 + 1, i0:i1 + 1]
        dx, dy, dv = x[1] - x[0], y[1] - y[0], v[1] - v[0]
        if 'BMAJ' in h.keys():
            bmaj = h['BMAJ'] * 3600. * dist  # au
            bmin = h['BMIN'] * 3600. * dist  # au
            bpa = h['BPA']  # deg
        else:
            bmaj, bmin, bpa = dy, -dx, 0
            print('No valid beam in the FITS file.')
        self.x, self.dx = x, dx
        self.y, self.dy = y, dy
        self.v, self.dv = v, dv
        self.data, self.header, self.sigma = d, h, sigma
        self.bmaj, self.bmin, self.bpa = bmaj, bmin, bpa
        self.cubefits, self.dist, self.vsys = cubefits, dist, vsys
        return {'x':x, 'y':y, 'v':v, 'data':d, 'header':h, 'sigma':sigma}

    def read_pvfits(self, pvfits: str,
                    dist: float = 1, vsys: float = 0,
                    xmax: float = 1e4,
                    vmin: float = -100, vmax: float = 100,
                    sigma: float = None) -> dict:
        """
        Read a position-velocity diagram in the FITS format.

        Parameters
        ----------
        pvfits : str
            Name of the input FITS file including the extension.
        dist : float
            Distance of the target, used to convert arcsec to au.
        vsys : float
            Systemic velocity of the target.
        xmax : float
            The positional axis is limited to (-xmax, xmax) in the unit of au.
        vmin : float
            The velocity axis is limited to (-vmax, vmax) in the unit of km/s.
        vmax : float
            The velocity axis is limited to (-vmax, vmax) in the unit of km/s.
        sigma : float
            Standard deviation of the FITS data. None means automatic.

        Returns
        ----------
        fitsdata : dict
            x (1D array), v (1D array), data (2D array), header, and sigma.
        """
        cc = constants.c.si.value
        f = fits.open(pvfits)[0]
        d, h = np.squeeze(f.data), f.header
        if sigma is None:
            sigma = np.mean([np.std(d[:2, 10:-10]), np.std(d[-2:, 10:-10]),
                             np.std(d[2:-2, :10]), np.std(d[2:-2, -10:])])
            print(f'sigma = {sigma:.3e}')
        x = (np.arange(h['NAXIS1'])-h['CRPIX1']+1)*h['CDELT1']+h['CRVAL1']
        v = (np.arange(h['NAXIS2'])-h['CRPIX2']+1)*h['CDELT2']+h['CRVAL2']
        x = x * dist  # au
        v = (1. - v / h['RESTFRQ']) * cc / 1.e3 - vsys  # km/s
        i0, i1 = np.argmin(np.abs(x + xmax)), np.argmin(np.abs(x - xmax))
        j0, j1 = np.argmin(np.abs(v - vmin)), np.argmin(np.abs(v - vmax))
        x, v, d = x[i0:i1 + 1], v[j0:j1 + 1], d[j0:j1 + 1, i0:i1 + 1]
        dx, dv = x[1] - x[0], v[1] - v[0]
        if 'BMAJ' in h.keys():
            dNyquist = (bmaj := h['BMAJ'] * 3600. * dist) / 2.  # au
            self.beam = [h['BMAJ'] * 3600. * dist, h['BMIN'] * 3600. * dist, h['BPA']]
        else:
            dNyquist = bmaj = np.abs(dx)  # au
            self.beam = None
            print('No valid beam in the FITS file.')
        self.x, self.dx = x, dx
        self.v, self.dv = v, dv
        self.data, self.header, self.sigma = d, h, sigma
        self.bmaj, self.dNyquist = bmaj, dNyquist
        self.bmin = h['BMIN'] * 3600. * dist
        self.pvfits, self.dist, self.vsys = pvfits, dist, vsys
        return {'x':x, 'v':v, 'data':d, 'header':h, 'sigma':sigma}

    def get_PV(self, cubefits: str = None,
               pa: float = 0, center: str = None,
               dist: float = 1, vsys: float = 0,
               xmax: float = 1e4,
               vmin: float = -100, vmax: float = 100,
               sigma: float = None):
        if not (cubefits is None):
            self.read_cubefits(cubefits, center, dist, vsys,
                               xmax, xmax, vmin, vmax, sigma)
        x, y, v = self.x, self.y, self.v
        sigma, d = self.sigma, self.data
        n = np.floor(xmax / self.dy)
        r = (np.arange(2 * n + 1) - n) * self.dy
        ry = r * np.cos(np.radians(pa))
        rx = r * np.sin(np.radians(pa))
        dpvmajor = [None] * len(v)
        dpvminor = [None] * len(v)
        for i in range(len(v)):
            interp = RGI((-x, y), d[i], bounds_error=False)
            dpvmajor[i] = interp((-rx, ry))
            dpvminor[i] = interp((ry, rx))
        self.dpvmajor = np.array(dpvmajor)
        self.dpvminor = np.array(dpvminor)
        self.x = r
    
    def put_PV(self, pvmajorfits: str, pvminorfits: str,
               dist: float, vsys: float,
               rmax: float, vmin: float, vmax: float, sigma: float,
               dNsampling = [5, 1]):
        self.read_pvfits(pvmajorfits, dist, vsys, rmax, vmin, vmax, sigma)
        if dNsampling is not None: self.sampling(dNsampling)
        self.dpvmajor = self.data
        self.read_pvfits(pvminorfits, dist, vsys, rmax, vmin, vmax, sigma)
        if dNsampling is not None: self.sampling(dNsampling)
        self.dpvminor = self.data


    def sampling(self, steps):
        x_smpl, y_smpl = steps
        x_smpl = int(self.bmin / x_smpl / self.dx )
        y_smpl = int(1. / y_smpl)
        if x_smpl == 0: x_smpl = 1
        if y_smpl == 0: y_smpl = 1
        #print(x_smpl, self.bmin, self.dx)
        self.data = self.data[y_smpl//2::y_smpl, x_smpl//2::x_smpl]
        self.v = self.v[y_smpl//2::y_smpl]
        self.x = self.x[x_smpl//2::x_smpl]
        self.dx = self.x[1] - self.x[0]
        self.dv = self.v[1] - self.v[0]

    '''
    def fitting(self, incl: float = 90,
                Mstar_range: list = [0.01, 10],
                Rc_range: list = [1, 1000],
                alphainfall_range: list = [0.01, 1],
                Mstar_fixed: float = None,
                Rc_fixed: float = None,
                alphainfall_fixed: float = None,
                cutoff: float = 5, vmask: list = [0, 0],
                figname: str = 'PVsilhouette',
                show: bool = False,
                progressbar: bool = True,
                kwargs_emcee_corner: dict = {}):
        majobs = np.where(self.dpvmajor > cutoff * self.sigma, 1, 0)
        minobs = np.where(self.dpvminor > cutoff * self.sigma, 1, 0)
        x, v = np.meshgrid(self.x, self.v)
        def minmax(a: np.ndarray, b: np.ndarray, s: str, m: np.ndarray):
            rng = a[(b >= 0 if s == '+' else b < 0) * (m > 0.5)]
            if len(rng) == 0:
                return 0, 0
            else:
                return np.min(rng), np.max(rng)
        rng = np.array([[[minmax(a, b, s, m)
                          for m in [majobs, minobs]]
                         for s in ['-', '+']]
                        for a, b in zip([x, v], [v, x])])
        def combine(r: np.ndarray):
            return np.min(r[:, 0]), np.max(r[:, 1])
        rng = [[combine(r) for r in rr] for rr in rng]
        mask = [[(s * a > 0) * ((b < r[0]) + (r[1] < b))
                 for s, r in zip([-1, 1], rr)]
                for a, b, rr in zip([v, x], [x, v], rng)]
        mask = np.sum(mask, axis=(0, 1)) + (vmask[0] < v) * (v < vmask[1])
        majobs = np.where(mask, np.nan, majobs)
        minobs = np.where(mask, np.nan, minobs)
        majsig = 1
        minsig = 1
        def calcchi2(majmod: np.ndarray, minmod: np.ndarray):
            chi2 =   np.nansum((majobs - majmod)**2 / majsig**2) \
                   + np.nansum((minobs - minmod)**2 / minsig**2)
            return chi2
        
        chi2max1 = calcchi2(np.ones_like(majobs), np.ones_like(minobs))
        chi2max0 = calcchi2(np.zeros_like(majobs), np.zeros_like(minobs))
        chi2max = np.min([chi2max0, chi2max1])
        def getquad(m):
            nv, nx = np.shape(m)
            q =   np.sum(m[:nv//2, :nx//2]) + np.sum(m[nv//2:, nx//2:]) \
                - np.sum(m[nv//2:, :nx//2]) - np.sum(m[:nv//2, nx//2:])
            return int(np.sign(q))
        majquad = getquad(self.dpvmajor)
        minquad = getquad(self.dpvminor) * (-1)
        def makemodel(Mstar, Rc, alphainfall, outputvel=False):
            a = velmax(self.x, Mstar=Mstar, Rc=Rc,
                       alphainfall=alphainfall, incl=incl)
            major = []
            for min, max in zip(a['major']['vlosmin'], a['major']['vlosmax']):
                major.append(np.where((min < self.v) * (self.v < max), 1, 0))
            major = np.transpose(major)[:, ::majquad]
            minor = []
            for min, max in zip(a['minor']['vlosmin'], a['minor']['vlosmax']):
                minor.append(np.where((min < self.v) * (self.v < max), 1, 0))
            minor = np.transpose(minor)[:, ::minquad]
            if outputvel:
                return major, minor, a
            else:
                return major, minor
        p_fixed = np.array([Mstar_fixed, Rc_fixed, alphainfall_fixed])
        if None in p_fixed:
            labels = np.array(['log Mstar', 'log Rc', r'log $\alpha$'])
            labels = labels[p_fixed == None]
            kwargs0 = {'nwalkers_per_ndim':16, 'nburnin':100, 'nsteps':500,
                       'rangelevel':None, 'labels':labels,
                       'figname':figname+'.corner.png', 'show_corner':show,}
            kwargs = dict(kwargs0, **kwargs_emcee_corner)
            if progressbar:
                total = kwargs['nwalkers_per_ndim'] * len(p_fixed[p_fixed == None])
                total *= kwargs['nburnin'] + kwargs['nsteps'] + 2
                bar = tqdm(total=total)
                bar.set_description('Within the ranges')
            def lnprob(p):
                if progressbar:
                    bar.update(1)
                q = p_fixed.copy()
                q[p_fixed == None] = 10**p
                chi2 = calcchi2(*makemodel(*q))
                return -np.inf if chi2 > chi2max else -0.5 * chi2
            plim = np.array([Mstar_range, Rc_range, alphainfall_range])
            plim = np.log10(plim[p_fixed == None]).T
            mcmc = emcee_corner(plim, lnprob, simpleoutput=False, **kwargs)
            if np.isinf(lnprob(mcmc[0])):
                print('No model is better than the all-0 or all-1 models.')
            popt = p_fixed.copy()
            popt[p_fixed == None] = 10**mcmc[0]
            plow = p_fixed.copy()
            plow[p_fixed == None] = 10**mcmc[1]
            phigh = p_fixed.copy()
            phigh[p_fixed == None] = 10**mcmc[3]
        else:
            popt = p_fixed
            plow = p_fixed
            phigh = p_fixed
        self.popt = popt
        self.plow = plow
        self.phigh = phigh
        print(f'M* = {plow[0]:.2f}, {popt[0]:.2f}, {phigh[0]:.2f} Msun')
        print(f'Rc = {plow[1]:.0f}, {popt[1]:.0f}, {phigh[1]:.0f} au')
        print(f'alpha = {plow[2]:.2f}, {popt[2]:.2f}, {phigh[2]:.2f}')

        majmod, minmod, a = makemodel(*popt, outputvel=True)
        fig = plt.figure()
        ax = fig.add_subplot(1, 2, 1)
        z = np.where(mask, -(mask.astype('int')), (majobs - majmod)**2)
        ax.pcolormesh(self.x, self.v, z, cmap='bwr', vmin=-1, vmax=1, alpha=0.1)
        ax.contour(self.x, self.v, self.dpvmajor,
                   levels=np.arange(1, 10) * 3 * self.sigma, colors='k')
        ax.plot(self.x * majquad, a['major']['vlosmax'], '-r')
        ax.plot(self.x * majquad, a['major']['vlosmin'], '-r')
        ax.set_xlabel('major offset (au)')
        ax.set_ylabel(r'$V-V_{\rm sys}$ (km s$^{-1}$)')
        ax.set_ylim(np.min(self.v), np.max(self.v))
        ax = fig.add_subplot(1, 2, 2)
        z = np.where(mask, -(mask.astype('int')), (minobs - minmod)**2)
        ax.pcolormesh(self.x, self.v, z, cmap='bwr', vmin=-1, vmax=1, alpha=0.1)
        ax.contour(self.x, self.v, self.dpvminor,
                   levels=np.arange(1, 10) * 3 * self.sigma, colors='k')
        ax.plot(self.x * minquad, a['minor']['vlosmax'], '-r')
        ax.plot(self.x * minquad, a['minor']['vlosmin'], '-r')
        ax.set_xlabel('minor offset (au)')
        ax.set_ylim(self.v.min(), self.v.max())
        ax.set_title(r'$M_{*}$'+f'={popt[0]:.2f}'+r'$M_{\odot}$'
            +', '+r'$R_{c}$'+f'={popt[1]:.0f} au'
            +'\n'+r'$\alpha$'+f'={popt[2]:.2f}'
            +', '+r'$\alpha ^{2} M_{*}$'+f'={popt[0] * popt[2]**2:.2}')
        fig.tight_layout()
        fig.savefig(figname + '.model.png')
        if show: plt.show()
    '''


    def check_modelgrid(self, nsubgrid: float = 1, 
        n_nest: list = None, reslim: float = 5):
        # model grid
        mpvd = MockPVD(self.x, self.x, self.v, 
            nsubgrid = nsubgrid, nnest = n_nest, 
            beam = self.beam, reslim = reslim)
        mpvd.grid.gridinfo()


    def fit_mockpvd(self, 
                incl: float = 89.,
                Mstar_range: list = [0.01, 10],
                Rc_range: list = [1., 1000.],
                alphainfall_range: list = [0.0, 1],
                fflux_range: list = [0.3, 3.],
                log_ftau_range: list = [-1., 3.],
                log_frho_range: list = [-1., 4.],
                sig_mdl_range: list = [0., 10.],
                fixed_params: dict = {'Mstar': None, 
                'Rc': None, 'alphainfall': None, 'fflux': None,
                'log_ftau': None, 'log_frho': None, 'sig_mdl': None},
                vmask: list = [0, 0],
                filename: str = 'PVsilhouette',
                show: bool = False,
                progressbar: bool = True,
                kwargs_emcee_corner: dict = {},
                signmajor = None, signminor = None,
                pa_maj = None, pa_min = None,
                beam = None, linewidth = None,
                p0 = None,
                nsubgrid = 1, n_nest = [3, 3], reslim = 5):
        # Observed PV diagrams
        majobs = self.dpvmajor.copy()
        minobs = self.dpvminor.copy()
        # correction factor for over sampling
        beam_area = np.pi/(4.*np.log(2.)) * self.bmaj * self.bmin # beam area
        Rarea = beam_area / self.dx / self.dx # area ratio


        # grid & mask
        x, v = np.meshgrid(self.x, self.v)
        '''
        def minmax(a: np.ndarray, b: np.ndarray, s: str, m: np.ndarray):
            rng = a[(b >= 0 if s == '+' else b < 0) * (m > 0.5)]
            if len(rng) == 0:
                return 0, 0
            else:
                return np.min(rng), np.max(rng)
        rng = np.array([[[minmax(a, b, s, m)
                          for m in [majobs, minobs]]
                         for s in ['-', '+']]
                        for a, b in zip([x, v], [v, x])])
        def combine(r: np.ndarray):
            return np.min(r[:, 0]), np.max(r[:, 1])
        rng = [[combine(r) for r in rr] for rr in rng]
        mask = [[(s * a > 0) * ((b < r[0]) + (r[1] < b))
                 for s, r in zip([-1, 1], rr)]
                for a, b, rr in zip([v, x], [x, v], rng)]
        '''
        mask = (vmask[0] < v) * (v < vmask[1])
        majobs = np.where(mask, np.nan, majobs)
        minobs = np.where(mask, np.nan, minobs)


        # define chi2
        majsig, minsig = self.sigma, self.sigma
        def calcchi2(majmod: np.ndarray, minmod: np.ndarray, majsig: float, minsig: float):
            chi2 = np.nansum((majobs - majmod)**2 / majsig**2) \
                   + np.nansum((minobs - minmod)**2 / minsig**2)
            return chi2 / np.sqrt(Rarea) # correct over sampling


        # get quadrant
        majquad = getquad(self.dpvmajor) if signmajor is None else signmajor
        minquad = getquad(self.dpvminor) * (-1) if signminor is None else signminor
        obsmax = max(np.nanmax(majobs), np.nanmax(minobs))


        # model
        mpvd = MockPVD(self.x, self.x, self.v, 
            nsubgrid = nsubgrid, nnest = n_nest, 
            beam = self.beam, reslim = reslim)
        rout = np.nanmax(self.x)
        def makemodel(Mstar, Rc, alphainfall, fflux, log_ftau, log_frho):
            major, minor = mpvd.generate_mockpvd(
                Mstar, Rc, alphainfall, 
                fflux = fflux * obsmax, frho = 10.**log_frho, ftau = 10.**log_ftau,
                incl = incl, withkepler = True, linewidth = linewidth,
                rout = rout, pa = [pa_maj, pa_min],
                axis = 'both')
            # quadrant
            major = major[:, ::majquad] #[:,step//2::step]
            minor = minor[:, ::minquad] #[:,step//2::step]
            return major, minor


        # Fitting
        _fixed_params = {'Mstar': None, 
        'Rc': None, 'alphainfall': None, 'fflux': None,
        'log_ftau': None, 'log_frho': None, 'sig_mdl': None}
        _fixed_params.update(fixed_params)
        p_fixed = np.array(list(_fixed_params.values()))
        #p_fixed = np.array([Mstar_fixed, Rc_fixed, alphainfall_fixed, 
        #    fflux_fixed, log_ftau_fixed, log_frho_fixed, sig_mdl_fixed])
        if None in p_fixed:
            labels = np.array(['Mstar', 'Rc', r'$\alpha$', r'$f_\mathrm{flux}$', 
                r'log $f_\tau$', r'log $f_\rho$', r'$\sigma_\mathrm{model}$'])
            labels = labels[p_fixed == None]
            kwargs0 = {'nwalkers_per_ndim':4, 'nburnin':500, 'nsteps':500,
                       'rangelevel': None, 'labels':labels,
                       'figname':filename+'.corner.png', 'show_corner':show,
                       }
            kwargs = dict(kwargs0, **kwargs_emcee_corner)
            # progress bar
            if progressbar:
                total = kwargs['nwalkers_per_ndim'] * len(p_fixed[p_fixed == None])
                total *= kwargs['nburnin'] + kwargs['nsteps']
                bar = tqdm(total=total)
                bar.set_description('Within the ranges')
            # Modified log likelihood
            def lnprob(p):
                if progressbar:
                    bar.update(1)
                # parameter
                q = p_fixed.copy()
                q[p_fixed == None] = p # in linear scale
                # updated sigma
                majsig2 = majsig**2. + q[-1]**2.
                minsig2 = minsig**2. + q[-1]**2.
                # make model
                majmod, minmod = makemodel(*q[:-1])
                return - 0.5 * (np.nansum((majobs - majmod)**2 / majsig2 + np.log(2.*np.pi*majsig2))\
                    + np.nansum((minobs - minmod)**2 / minsig2 + np.log(2.*np.pi*minsig2))) / np.sqrt(Rarea)
            # prior
            sig_mdl_range = np.array(sig_mdl_range) * self.sigma
            plim = np.array([Mstar_range, Rc_range, alphainfall_range, 
                fflux_range, log_ftau_range, log_frho_range, list(sig_mdl_range)])
            plim = plim[p_fixed == None].T

            # run mcmc fitting
            mcmc = emcee_corner(plim, lnprob, simpleoutput=False, **kwargs)

            # best parameters & errors
            popt = p_fixed.copy()
            popt[p_fixed == None] = mcmc[0]
            plow = p_fixed.copy()
            plow[p_fixed == None] = mcmc[1]
            pmid = p_fixed.copy()
            pmid[p_fixed == None] = mcmc[2]
            phigh = p_fixed.copy()
            phigh[p_fixed == None] = mcmc[3]
        else:
            popt = p_fixed
            plow = p_fixed
            pmid = p_fixed
            phigh = p_fixed
        self.popt = popt
        self.plow = plow
        self.pmid = pmid
        self.phigh = phigh
        print(f'M* = {plow[0]:.2f}, {popt[0]:.2f}, {phigh[0]:.2f} Msun')
        print(f'Rc = {plow[1]:.0f}, {popt[1]:.0f}, {phigh[1]:.0f} au')
        print(f'alpha = {plow[2]:.2f}, {popt[2]:.2f}, {phigh[2]:.2f}')
        print(f'f_flux = {plow[3]:.2f}, {popt[3]:.2f}, {phigh[3]:.2f}')
        print(f'f_tau = {plow[4]:.2f}, {popt[4]:.2f}, {phigh[4]:.2f}')
        print(f'f_rho = {plow[5]:.2f}, {popt[5]:.2f}, {phigh[5]:.2f}')


        # write out result
        self.writeout_fitres(filename + '.popt')


        # plot
        figs = self.plot_pvds(color = 'model', contour = 'obs',
            filename = filename, incl = incl, vmask = vmask, pa_maj = pa_maj, pa_min = pa_min,
            linewidth = linewidth, signmajor = signmajor, signminor = signminor,
            show = show, set_title = True, nsubgrid = nsubgrid, n_nest = n_nest, reslim = reslim)


    def writeout_fitres(self, fout:str = 'PVsilhouette.popt'):
        '''
        Write out fitting result.

        Parameters
        ----------
        fout (str): Output file name without the file extension.
        '''
        if hasattr(self, 'popt'):
            labels = np.array(['Mstar', 'Rc', 'alpha', 
                'fflux', 'log_ftau', 'log_frho', 'sig_mdl'])
            header = '# popt plow pmid phigh\n'

            with open(fout+'.txt', 'w+') as f:
                f.write(header)
                np.savetxt(f, 
                    np.array([labels, self.popt, self.plow, self.pmid, self.phigh]).T,
                    fmt = '%s')#, '%13.6e', '%13.6e', '%13.6e', '%13.6e'])
        else:
            print('ERROR\twriteout_fitres: No optimized parameters are found.')
            print('ERROR\twriteout_fitres: Run fitting first.')
            return 0


    def read_fitres(self, f: str):
        '''
        Read fitting result.

        Parameter
        ---------
        f (str): Path to a file containing the fitting result.
        '''
        self.popt, self.plow, self.pmid, self.phigh = \
        np.genfromtxt(f, dtype = float, comments = '#', unpack = True,
            usecols = (1,2,3,4))


    def plot_pvds(self, filename = 'PVsilhouette', 
        color = 'model', contour = 'obs', incl = 89.,
        vmask = [0., 0.], pa_maj = None, pa_min = None, linewidth = None,
        signmajor: int = None, signminor: int = None, 
        cmap = 'viridis', cmap_residual = 'bwr', ext = '.png',
        set_title = False,
        show = False, nsubgrid = 1, n_nest = [3, 3], reslim = 5,
        shadecolor = 'white', clevels = None):
        '''
        Plot observed and model PV diagrams.
        '''

        # data
        majobs, minobs = self.dpvmajor.copy(), self.dpvminor.copy()

        # get quadrant
        majquad = getquad(self.dpvmajor) if signmajor is None else signmajor
        minquad = getquad(self.dpvminor) * (-1) if signminor is None else signminor
        obsmax = max(np.nanmax(majobs), np.nanmax(minobs))

        # model
        mpvd = MockPVD(self.x, self.x, self.v, 
            nsubgrid = nsubgrid, nnest = n_nest, 
            beam = self.beam, reslim = reslim)
        rout = np.nanmax(self.x)
        def makemodel(Mstar, Rc, alphainfall, fflux, log_ftau, log_frho):
            major, minor = mpvd.generate_mockpvd(
                Mstar, Rc, alphainfall, 
                fflux = fflux * obsmax, frho = 10.**log_frho, ftau = 10.**log_ftau,
                incl = incl, withkepler = True, linewidth = linewidth,
                rout = rout, pa = [pa_maj, pa_min],
                axis = 'both')
            # quadrant
            major = major[:, ::majquad] #[:,step//2::step]
            minor = minor[:, ::minquad] #[:,step//2::step]
            return major, minor


        # grid/data/mask/sigma
        x, v = np.meshgrid(self.x, self.v)
        mask = (vmask[0] < v) * (v < vmask[1]) # velocity mask
        majsig, minsig = self.sigma, self.sigma

        if 'model' in [color, contour]:
            # check if fitting result exists
            if hasattr(self, 'popt'):
                pass
            else:
                print('ERROR\twriteout_fitres: No optimized parameters are found.')
                print('ERROR\twriteout_fitres: Run fitting or read fitting result first.')
                return 0
            # model pv diagrams
            majmod, minmod = makemodel(*self.popt[:-1])
            # residual
            majres = np.where(mask, -(mask.astype('int')), (majobs - majmod) / majsig)
            minres = np.where(mask, -(mask.astype('int')), (minobs - minmod) / minsig)
            plot_residual = True
            outlabel = '.model'
        else:
            plot_residual = False
            outlabel = '.obs'


        if clevels is None: clevels = np.arange(1, 10) * 3 * self.sigma
        def makeplots(data_color, data_contour, cmap,
            vmin = None, vmax = None, vmask = None, alpha = 1.):
            # set figure
            fig, axes = plt.subplots(1, 2,)
            ax1, ax2 = axes

            # major
            im = ax1.pcolormesh(self.x, self.v, data_color[0], 
                cmap=cmap, vmin = vmin, vmax = vmax,
                alpha = alpha, rasterized = True)
            #cax = ax1.inset_axes([1.0, 0., 0.05, 1.]) # x0, y0, dx, dy
            #fig.colorbar(im, cax=cax)
            ax1.contour(self.x, self.v, data_contour[0],
                       levels = clevels, colors='k')
            ax1.set_xlabel('Major offset (au)')
            ax1.set_ylabel(r'$V-V_{\rm sys}$ (km s$^{-1}$)')

            # minor
            im = ax2.pcolormesh(self.x, self.v, data_color[1], cmap=cmap, 
                vmin= vmin, vmax = vmax, alpha=alpha, rasterized=True)
            ax2.contour(self.x, self.v, data_contour[1],
                       levels = clevels, colors='k')
            cax2 = ax2.inset_axes([1.0, 0., 0.05, 1.]) # x0, y0, dx, dy
            fig.colorbar(im, cax=cax2)
            ax2.set_yticklabels('')
            ax2.set_xlabel('Minor offset (au)')

            for ax in axes:
                ax.set_xlim(np.min(self.x), np.max(self.x))
                ax.set_ylim(np.min(self.v), np.max(self.v))

            if vmask is not None:
                _v = self.v[ (self.v > vmask[0]) * (self.v < vmask[1])] # masked velocity ranges
                for ax in axes:
                    ax.fill_between(
                        self.x, np.full(len(self.x), np.min(_v) - 0.5 * self.dv), 
                        np.full(len(self.x), np.max(_v) + 0.5 * self.dv),
                        color = shadecolor, alpha = 0.6,
                        edgecolor = None,
                        )

            if set_title:
                ax2.set_title(r'$M_{*}$'+f'={self.popt[0]:.2f}'+r'$M_{\odot}$'
                    +', '+r'$R_{c}$'+f'={self.popt[1]:.0f} au'
                    +'\n'+r'$\alpha$'+f'={self.popt[2]:.2f}'
                    +', '+r'$\alpha ^{2} M_{*}$'+f'={self.popt[0] * self.popt[2]**2:.2}')

            return fig


        # color images and model images
        d_col = [majmod, minmod] if color == 'model' else [majobs, minobs]
        d_con = [majmod, minmod] if contour == 'model' else [majobs, minobs]


        figs = []
        # main plot
        vmin, vmax = np.nanmin(np.array(d_col)), np.nanmax(np.array(d_col))
        vmask = vmask if vmask[1] > vmask[0] else None
        fig = makeplots(d_col, d_con, cmap, vmin = vmin, vmax = vmax, 
            vmask = vmask, alpha = 0.8)
        fig.tight_layout()
        fig.savefig(filename + outlabel + ext, dpi = 300)
        figs.append(fig)
        if show: plt.show()

        # residual plot
        if plot_residual:
            d_col = [majres, minres] if color == 'model' else [majobs, minobs]
            d_con = [majres, minres] if contour == 'model' else [majobs, minobs]
            vmin, vmax = np.nanmin(np.array(d_col)), np.nanmax(np.array(d_col))
            # plot
            fig2 = makeplots(d_col, d_con, cmap_residual, 
                vmin = vmin, vmax = vmax, 
                vmask = None, alpha = 0.5)
            fig2.tight_layout()
            fig2.savefig(filename + '.residual' + ext, dpi = 300)
            figs.append(fig2)
            if show: plt.show()

        return figs


def getquad(m):
    '''
    Get quadrant
    '''
    nv, nx = np.shape(m)
    q = np.sum(m[:nv//2, :nx//2]) + np.sum(m[nv//2:, nx//2:]) \
        - np.sum(m[nv//2:, :nx//2]) - np.sum(m[:nv//2, nx//2:])
    return int(np.sign(q))
