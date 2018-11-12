"""Script de comparaison des biais du model de Hapke."""

import os.path
import logging

import numpy as np
import coloredlogs

from Core import em_is_gllim, noise_GD
from Core.gllim import jGLLiM
from experiences.noise_estimation import NoiseEstimation
from tools import context
from tools.experience import Experience

SAVEPATH = "/scratch/WORK/comparaison"


def train_predict(noise_mean, noise_cov, filename, retrain=True):
    exp, gllim = Experience.setup(context.LabContextOlivine, 40, partiel=(0, 1, 2, 3), with_plot=True,
                                  regenere_data=retrain, noise_mean=noise_mean, noise_cov=noise_cov, N=50000,
                                  method="sobol",
                                  mode="r" if retrain else "l", init_local=10,
                                  sigma_type="full", gamma_type="full", gllim_cls=jGLLiM)

    MCMC_X, Std = exp.context.get_result()
    Yobs = exp.context.get_observations()

    Xmean, Covs, Xweight = gllim.merged_prediction(Yobs)

    Xmean = exp.context.to_X_physique(Xmean)
    Xweight = np.array([exp.context.to_X_physique(X) for X in Xweight])
    Covs = np.array([exp.context.to_Cov_physique(C) for C in Covs])

    corrected_X = exp.context.normalize_X(Xmean * (Xmean <= 1) + 1 * (Xmean > 1))
    c = exp.mesures._relative_error(exp.context.F(corrected_X) + noise_mean, Yobs)
    y_error_mean = np.mean(c)
    title = f"Y error : {y_error_mean:.4f}"

    path = os.path.join(SAVEPATH, filename)

    varlims = [(0, 0.6), (-0.2, 0.7), (0, 20), (0.55, 1.1)]
    exp.results.prediction_by_components(Xmean, Covs, exp.context.wavelengths, Xweight=Xweight,
                                         xtitle="longeur d'onde ($\mu$m)", varlims=varlims,
                                         Xref=MCMC_X, StdRef=Std, title=title, savepath=path,
                                         is_merged_pred=True)


noise_GD.Ntrain = 1000000
em_is_gllim.INIT_MEAN_NOISE = 2243303186
em_is_gllim.INIT_COV_NOISE = 2308448170

noise_cov0 = 0.001
noise_mean0 = 0

exp = NoiseEstimation(context.LabContextOlivine, "obs", "full", "is_gllim")
noise_mean1, noise_cov1 = exp.get_last_params(average_over=1)

exp = NoiseEstimation(context.MergedLabObservations, "obs", "full", "is_gllim")
noise_mean2, noise_cov2 = exp.get_last_params(average_over=1)

exp = NoiseEstimation(context.LabContextOlivine, "obs", "diag", "gd")
noise_mean3, noise_cov3 = exp.get_last_params(average_over=400)

exp = NoiseEstimation(context.MergedLabObservations, "obs", "diag", "gd")
noise_mean4, noise_cov4 = exp.get_last_params(average_over=400)

if __name__ == '__main__':
    coloredlogs.install(level=logging.DEBUG, fmt="%(module)s %(asctime)s : %(levelname)s : %(message)s",
                        datefmt="%H:%M:%S")

    train_predict(noise_mean0, noise_cov0, "Olivine-sansBiais.png", retrain=True)
    train_predict(noise_mean1, noise_cov1, "Olivine-GD-biaisOlivine.png", retrain=True)
    train_predict(noise_mean2, noise_cov2, "Olivine-GD-biaisCommun.png", retrain=True)
    train_predict(noise_mean3, noise_cov3, "Olivine-ISGLLiM-biaisOlivine.png", retrain=True)
    train_predict(noise_mean4, noise_cov4, "Olivine-ISGLLiM-biaisCommun.png", retrain=True)
