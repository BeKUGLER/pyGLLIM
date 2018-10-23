"""Implements a crossed EM - GLLiM algorith to evaluate noise in model.
Diagonal covariance is assumed"""
import logging
import time

import coloredlogs
import numba as nb
import numpy as np

from Core.gllim import jGLLiM
from Core.probas_helper import chol_loggauspdf_diag, chol_loggausspdf_precomputed, \
    densite_melange_precomputed, cholesky_list
from tools import context

# GLLiM parameters
Ntrain = 40000
K = 40
init_X_precision_factor = 10
maxIterGlliM = 100
stoppingRatioGLLiM = 0.005


N_sample_IS = 100000

INIT_COV_NOISE = 0.005  # initial noise
INIT_MEAN_NOISE = 0  # initial noise offset
maxIter = 100

NO_IS = False
"""If it's True, dont use Importance sampling"""

def _gllim_step(cont: context.abstractHapkeModel, current_noise_cov, current_noise_mean, current_theta):
    gllim = jGLLiM(K, sigma_type="full", stopping_ratio=stoppingRatioGLLiM)
    Xtrain, Ytrain = cont.get_data_training(Ntrain)
    Ytrain = cont.add_noise_data(Ytrain, covariance=current_noise_cov, mean=current_noise_mean)

    gllim.fit(Xtrain, Ytrain, current_theta, maxIter=maxIterGlliM)
    gllim.inversion()
    return gllim


@nb.jit(nopython=True, nogil=True, fastmath=True, cache=True)
def _clean_mean_vector(Gx, w, mask_x):
    N, L = Gx.shape
    mask1 = np.empty(N, dtype=np.bool_)
    for i in range(N):
        mask1[i] = not np.isfinite(Gx[i]).all()

    mask2 = ~ np.isfinite(w)
    mask = mask_x | mask1 | mask2
    w[mask] = 0
    Gx[mask] = np.zeros(L)
    w = w.reshape((-1, 1))
    return np.sum(Gx * w, axis=0) / np.sum(w)


@nb.jit(nopython=True, nogil=True, fastmath=True, cache=True)
def _clean_mean_matrix(Gx, w, mask_x):
    N, L, _ = Gx.shape
    mask1 = np.empty(N, dtype=np.bool_)
    for i in range(N):
        mask1[i] = not np.isfinite(Gx[i]).all()

    mask2 = ~ np.isfinite(w)
    mask = mask_x | mask1 | mask2
    w[mask] = 0
    Gx[mask] = np.zeros((L, L))
    w = w.reshape((-1, 1, 1))
    return np.sum(Gx * w, axis=0) / np.sum(w)


@nb.njit(nogil=True, fastmath=True, cache=True)
def _helper_mu(X, weights, means, gllim_chol_covs, log_p_tilde, FX, mask_x, y):
    q = densite_melange_precomputed(X, weights, means, gllim_chol_covs)
    p_tilde = np.exp(log_p_tilde)
    wsi = p_tilde / q  # Calcul des poids
    G1 = y.reshape((1, -1)) - FX  # estimateur de mu
    esp_mui = _clean_mean_vector(G1, wsi, mask_x)
    return esp_mui, wsi


@nb.njit(nogil=True, fastmath=True, cache=True)
def _helper_mu_NoIS(FX, mask_x, y):
    G1 = y.reshape((1, -1)) - FX  # estimateur de mu
    Ns, _ = G1.shape
    wsi = np.ones(Ns) / Ns
    esp_mui = _clean_mean_vector(G1, wsi, mask_x)
    return esp_mui


@nb.njit(nogil=True, cache=True)
def extend_array(vector, Ns):
    D = vector.shape[0]
    extended = np.zeros((Ns, D))
    for i in range(Ns):
        extended[i] = np.copy(vector)
    return extended


@nb.njit(nogil=True, parallel=True, fastmath=True)
def _mu_step_diag(Yobs, Xs, meanss, weightss, FXs, mask, gllim_covs, current_mean, current_cov):
    Ny, Ns, D = FXs.shape

    gllim_chol_covs = cholesky_list(gllim_covs)
    ws = np.zeros((Ny, N_sample_IS))
    esp_mu = np.zeros((Ny, D))

    current_mean_broad = extend_array(current_mean, Ns)

    for i in nb.prange(Ny):
        y = Yobs[i]
        X = Xs[i]
        means = meanss[i]
        weights = weightss[i]
        FX = FXs[i]
        mask_x = mask[i]
        arg = FX + current_mean_broad
        log_p_tilde = chol_loggauspdf_diag(arg.T, y, current_cov)
        esp_mu[i], ws[i] = _helper_mu(X, weights, means, gllim_chol_covs, log_p_tilde, FX, mask_x, y)
    maximal_mu = np.sum(esp_mu, axis=0) / Ny
    return maximal_mu, ws


def _mu_step_NoIS(Yobs, FXs, mask):
    Ny, Ns, D = FXs.shape
    esp_mu = np.zeros((Ny, D))
    for i in nb.prange(Ny):
        y = Yobs[i]
        FX = FXs[i]
        mask_x = mask[i]
        esp_mu[i] = _helper_mu_NoIS(FX, mask_x, y)
    maximal_mu = np.sum(esp_mu, axis=0) / Ny
    return maximal_mu


@nb.njit(nogil=True, parallel=True, fastmath=True)
def _mu_step_full(Yobs, Xs, meanss, weightss, FXs, mask, gllim_covs, current_mean, current_cov):
    Ny, Ns, D = FXs.shape

    gllim_chol_covs = cholesky_list(gllim_covs)
    chol_cov = np.linalg.cholesky(current_cov)
    ws = np.zeros((Ny, N_sample_IS))
    esp_mu = np.zeros((Ny, D))

    current_mean_broad = extend_array(current_mean, Ns)

    for i in nb.prange(Ny):
        y = Yobs[i]
        X = Xs[i]
        means = meanss[i]
        weights = weightss[i]
        FX = FXs[i]
        mask_x = mask[i]
        arg = FX + current_mean_broad
        log_p_tilde = chol_loggausspdf_precomputed(arg.T, y, chol_cov)
        esp_mu[i], ws[i] = _helper_mu(X, weights, means, gllim_chol_covs, log_p_tilde, FX, mask_x, y)
    maximal_mu = np.sum(esp_mu, axis=0) / Ny
    return maximal_mu, ws


@nb.njit(nogil=True, parallel=True, fastmath=True)
def _sigma_step_diag(Yobs, FXs, ws, mask, maximal_mu):
    Ny, Ns, D = FXs.shape
    maximal_mu_broadcast = extend_array(maximal_mu, Ns)
    esp_sigma = np.zeros((Ny, D))

    for i in nb.prange(Ny):
        y = Yobs[i]
        FX = FXs[i]
        U = FX + maximal_mu_broadcast - extend_array(y, Ns)
        G3 = np.square(U)
        esp_sigma[i] = _clean_mean_vector(G3, ws[i], mask[i])

    maximal_sigma = np.sum(esp_sigma, axis=0) / Ny
    return maximal_sigma


def _sigma_step_diag_NoIS(Yobs, FXs, mask, maximal_mu):
    Ny, Ns, D = FXs.shape
    maximal_mu_broadcast = extend_array(maximal_mu, Ns)
    esp_sigma = np.zeros((Ny, D))

    wsi = np.ones(Ns) / Ns
    for i in nb.prange(Ny):
        y = Yobs[i]
        FX = FXs[i]
        U = FX + maximal_mu_broadcast - extend_array(y, Ns)
        G3 = np.square(U)
        esp_sigma[i] = _clean_mean_vector(G3, wsi, mask[i])

    maximal_sigma = np.sum(esp_sigma, axis=0) / Ny
    return maximal_sigma


@nb.njit(nogil=True, parallel=True, fastmath=True)
def _sigma_step_full(Yobs, FXs, ws, mask, maximal_mu):
    Ny, Ns, D = FXs.shape
    maximal_mu_broadcast = extend_array(maximal_mu, Ns)
    esp_sigma = np.zeros((Ny, D, D))

    for i in nb.prange(Ny):
        y = Yobs[i]
        FX = FXs[i]
        U = FX + maximal_mu_broadcast - extend_array(y, Ns)
        G3 = np.zeros((Ns, D, D))
        for j in range(Ns):
            u = U[j]
            G3[j] = u.reshape((-1, 1)).dot(u.reshape((1, -1)))

        esp_sigma[i] = _clean_mean_matrix(G3, ws[i], mask[i])

    maximal_sigma = np.sum(esp_sigma, axis=0) / Ny
    return maximal_sigma


def _sigma_step_full_NoIS(Yobs, FXs, mask, maximal_mu):
    Ny, Ns, D = FXs.shape
    maximal_mu_broadcast = extend_array(maximal_mu, Ns)
    esp_sigma = np.zeros((Ny, D, D))
    wsi = np.ones(Ns) / Ns

    for i in nb.prange(Ny):
        y = Yobs[i]
        FX = FXs[i]
        U = FX + maximal_mu_broadcast - extend_array(y, Ns)
        G3 = np.zeros((Ns, D, D))
        for j in range(Ns):
            u = U[j]
            G3[j] = u.reshape((-1, 1)).dot(u.reshape((1, -1)))

        esp_sigma[i] = _clean_mean_matrix(G3, wsi, mask[i])

    maximal_sigma = np.sum(esp_sigma, axis=0) / Ny
    return maximal_sigma


def _em_step(gllim, F, Yobs, current_cov, current_mean):
    Xs = gllim.predict_sample(Yobs, nb_per_Y=N_sample_IS)
    mask = ~ np.array([(np.all((0 <= x) * (x <= 1), axis=1) if x.shape[0] > 0 else None) for x in Xs])
    logging.debug(f"Average ratio of F-non-compatible samplings : {mask.sum(axis=1).mean() / N_sample_IS:.5f}")
    ti = time.time()

    meanss, weightss, _ = gllim._helper_forward_conditionnal_density(Yobs)
    gllim_covs = gllim.SigmakListS

    N, D = Yobs.shape
    FXs = np.empty((N, N_sample_IS, D))
    for i, (X, mask_x) in enumerate(zip(Xs, mask)):
        FX = F(X)
        FX[mask_x, :] = 0  # anyway, ws will be 0
        FXs[i] = FX
    logging.debug(f"Computation of F done in {time.time()-ti:.3f} s")
    ti = time.time()

    if current_cov.ndim == 1:
        maximal_mu, ws = _mu_step_diag(Yobs, Xs, meanss, weightss, FXs, mask, gllim_covs, current_mean, current_cov)
    else:
        maximal_mu, ws = _mu_step_full(Yobs, Xs, meanss, weightss, FXs, mask, gllim_covs, current_mean, current_cov)
    logging.debug(f"Noise mean estimation done in {time.time()-ti:.3f} s")

    ti = time.time()
    _sigma_step = _sigma_step_diag if current_cov.ndim == 1 else _sigma_step_full
    maximal_sigma = _sigma_step(Yobs, FXs, ws, mask, maximal_mu)
    logging.debug(f"Noise covariance estimation done in {time.time()-ti:.3f} s")
    return maximal_mu, maximal_sigma


def _em_step_NoIS(gllim, F, Yobs, current_cov, current_mean):
    Xs = gllim.predict_sample(Yobs, nb_per_Y=N_sample_IS)
    mask = ~ np.array([(np.all((0 <= x) * (x <= 1), axis=1) if x.shape[0] > 0 else None) for x in Xs])
    logging.debug(f"Average ratio of F-non-compatible samplings : {mask.sum(axis=1).mean() / N_sample_IS:.5f}")
    ti = time.time()

    N, D = Yobs.shape
    FXs = np.empty((N, N_sample_IS, D))
    for i, (X, mask_x) in enumerate(zip(Xs, mask)):
        FX = F(X)
        FX[mask_x, :] = 0  # anyway, ws will be 0
        FXs[i] = FX
    logging.debug(f"Computation of F done in {time.time()-ti:.3f} s")
    ti = time.time()

    maximal_mu = _mu_step_NoIS(Yobs, FXs, mask)
    logging.debug(f"Noise mean estimation done in {time.time()-ti:.3f} s")

    ti = time.time()
    _sigma_step = _sigma_step_diag_NoIS if current_cov.ndim == 1 else _sigma_step_full_NoIS
    maximal_sigma = _sigma_step(Yobs, FXs, mask, maximal_mu)
    logging.debug(f"Noise covariance estimation done in {time.time()-ti:.3f} s")
    return maximal_mu, maximal_sigma




def _init(cont: context.abstractHapkeModel, init_noise_cov, init_noise_mean):
    gllim = jGLLiM(K, sigma_type="full", verbose=False)
    Xtrain, Ytrain = cont.get_data_training(Ntrain)
    Ytrain = cont.add_noise_data(Ytrain, covariance=init_noise_cov, mean=init_noise_mean)  # 0 offset

    m = cont.get_X_uniform(K)
    rho = np.ones(gllim.K) / gllim.K
    precisions = init_X_precision_factor * np.array([np.eye(Xtrain.shape[1])] * gllim.K)
    rnk = gllim._T_GMM_init(Xtrain, 'random',
                            weights_init=rho, means_init=m, precisions_init=precisions)
    gllim.fit(Xtrain, Ytrain, {"rnk": rnk}, maxIter=1)
    return gllim.theta


def fit(Yobs, cont: context.abstractHapkeModel, cov_type="diag"):
    logging.info(f"""Starting noise estimation ({cov_type}) 
    With IS : {not NO_IS}
    Nobs = {len(Yobs)} , NSampleIS = {N_sample_IS}
    Initial covariance noise : {INIT_COV_NOISE} 
    Initial mean noise : {INIT_MEAN_NOISE}""")

    F = lambda X: cont.F(X, check=False)
    current_theta = _init(cont, INIT_COV_NOISE, INIT_MEAN_NOISE)
    base_cov = np.eye(cont.D) if cov_type == "full" else np.ones(cont.D)
    current_noise_cov, current_noise_mean = INIT_COV_NOISE * base_cov, INIT_MEAN_NOISE * np.ones(cont.D)
    history = [(current_noise_mean.tolist(), current_noise_cov.tolist())]
    for current_iter in range(maxIter):
        gllim = _gllim_step(cont, current_noise_cov, current_noise_mean, current_theta)
        if NO_IS:
            max_mu, max_sigma = _em_step_NoIS(gllim, F, Yobs, current_noise_cov, current_noise_mean)
        else:
            max_mu, max_sigma = _em_step(gllim, F, Yobs, current_noise_cov, current_noise_mean)
        log_sigma = max_sigma if cov_type == "diag" else np.diag(max_sigma)
        logging.info(f"""Iteration {current_iter+1}/{maxIter}. 
        New estimated OFFSET : {max_mu}
        New estimated COVARIANCE : {log_sigma}""")
        current_noise_cov, current_noise_mean = max_sigma, max_mu
        history.append((current_noise_mean.tolist(), current_noise_cov.tolist()))
    return history





def _profile():
    global maxIter, Nobs, N_sample_IS, INIT_COV_NOISE
    maxIter = 1
    Nobs = 500
    N_sample_IS = 100000
    cont = context.LabContextOlivine(partiel=(0, 1, 2, 3))

    _, Yobs = cont.get_data_training(Nobs)
    Yobs = cont.add_noise_data(Yobs, covariance=0.005, mean=0.1)
    Yobs = np.copy(Yobs, "C")  # to ensure Y is contiguous

    fit(Yobs, cont, cov_type="full")

def _debug():
    global maxIter, Nobs, N_sample_IS, INIT_COV_NOISE, NO_IS
    NO_IS = True
    maxIter = 2
    Nobs = 20
    N_sample_IS = 10000
    cont = context.LabContextOlivine(partiel=(0, 1, 2, 3))
    INIT_COV_NOISE = 0.005
    _, Yobs = cont.get_data_training(Nobs)
    Yobs = cont.add_noise_data(Yobs, covariance=0.005, mean=0.1)
    Yobs = np.copy(Yobs, "C")  # to ensure Y is contiguous

    fit(Yobs, cont, cov_type="full")

if __name__ == '__main__':
    coloredlogs.install(level=logging.DEBUG, fmt="%(module)s %(name)s %(asctime)s : %(levelname)s : %(message)s",
                        datefmt="%H:%M:%S")
    # _profile()
    _debug()
    # cont = context.InjectiveFunction(2)()
    # main(cont,obs_mode,"diag",no_save=False)
    # show_history(cont, obs_mode, "full")
    # show_history(cont, obs_mode, "diag")
    # INIT_COV_NOISE = 0.01
    # show_history("full")
    # show_history("diag")
    # INIT_COV_NOISE = 0.001
    # show_history("full")
    # show_history("diag")

    # cont = context.LabContextOlivine(partiel=(0, 1, 2, 3))
    # h = cont.geometries
    # np.savetxt("geometries_olivine.txt",h[:,0,:].T,fmt="%.1f")
    # INIT_COV_NOISE = 0.01
    # mean, cov = get_last_params(cont,"obs","full")
