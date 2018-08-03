# Description des variables utilisées dans le package sklearn
# precisions : les K matrices inverses des matrices de covariances
# n_components : K (nombre de gaussiennes du mélanges)
# n_features : Dimension des matrices de covariances (taille de Y : D)
# cov_chol : Matrice trinagulaire correspondant à la decomp de Cholesky de la matrice de covariance
# precisions_chol : Matrice triangulaire correspondant à la decomp de Cholesky de la matrice de precisions
# weights : Pi_k : coefficient de chaque zone
import json
import logging
import time

import coloredlogs
import numpy as np
import scipy.io

from Core.dgllim import dGLLiM
from Core.gllim import GLLiM, jGLLiM
from Core.log_gauss_densities import chol_loggausspdf
from Core.riemannian import RiemannianjGLLiM
from Core.sGllim import saGLLiM
from hapke import hapke_sym
from hapke.hapke_vect import Hapke_vect
from hapke.hapke_vect_opt import Hapke_vect as Hapke_opt
from plotting import graphiques
from tools.context import WaveFunction, HapkeGonio1468, VoieS, HapkeContext, InjectiveFunction
from tools.experience import SecondLearning, Experience, _train_K_N
from tools.interface_R import is_egal
from tools.measures import Mesures

np.set_printoptions(precision=20,suppress=False)


def test_equivalence_GMM_GGLim():
    rho = np.arange(10)
    m = np.random.random_sample((10, 7))
    T = np.array([np.tril(np.random.random_sample((7, 7))) for i in range(10)])
    V = np.matmul(T, T.transpose((0, 2, 1)))

    t = GLLiM.GMM_to_GLLiM(rho, m, V, 4)
    u = GLLiM.GLLiM_to_GGM(*t)
    t2 = GLLiM.GMM_to_GLLiM(*u, 4)

    assert np.allclose(u[0], rho)
    assert np.allclose(u[1], m)
    assert np.allclose(u[2], V)

    assert np.allclose(t[0], t2[0])
    assert np.allclose(t[1], t2[1])
    assert np.allclose(t[2], t2[2])
    assert np.allclose(t[3], t2[3])
    assert np.allclose(t[4], t2[4])
    assert np.allclose(t[5], t2[5])







# compare_EM()
# test_GGLiM()
# test_equivalence_GMM_GGLim() # OK
# ir = compare_R() # OK

a = np.ones((200000,11)) * 0.413548

def io_json_write():
    with open("_testf.json",'w') as f:
        json.dump(a.tolist(),f)

def io_json_load():
    with open("_testf.json") as f:
        a = json.load(f)
        a = np.array(a)

def io_scipy_write():
    scipy.io.savemat("_testf.mat",{"a":a})

def io_scipy_load():
    a = scipy.io.loadmat("_testf.mat")["a"]


def test():
    mu = np.ones(11)
    T = np.tril(np.ones((11, 1&1))) * 0.456
    cov = np.dot(T, T.T)
    d = chol_loggausspdf(a.T,mu[:,None],cov)


def _compare_Fsym():
    "Check if symbolic F evaluates the same as nuemrical F"
    c = HapkeContext(None)
    symF = hapke_sym.lambdify_F(c)
    X = c.get_X_sampling(100000)
    np.seterr(divide="raise",over="print")
    Ysym = symF(*X.T)[:,0,:].T
    Y = c.F(X)
    print(np.abs(Ysym - Y).max())
    assert np.allclose(Ysym,Y)




def simple_function():
    exp = Experience(WaveFunction, partiel=None, verbose=True, with_plot=True)
    exp.load_data(regenere_data=True, with_noise=None, N=10000)
    # exp.NB_MAX_ITER = 200
    dGLLiM.dF_hook = exp.context.dF
    gllim = exp.load_model(100, mode="r", track_theta=False, init_local=None, multi_init=None,
                           gamma_type="full", gllim_cls=RiemannianjGLLiM)

    # assert np.allclose(gllim.AkList, np.array([exp.context.dF(c) for c in gllim.ckList]))

    x = np.array([0.55])
    y = exp.context.F(x[None,:])

    # exp.mesures.evolution_approx(x)
    # # print(exp.mesures.run_mesures(gllim))
    # thetas, LLs = exp.archive.load_tracked_thetas()
    # exp.mesures.evolution_illustration(thetas, cached=True)

    # exp.mesures.compareF(gllim)
    # exp.mesures.plot_modal_prediction(gllim,[0.01,0.001])
    # exp.mesures.plot_mean_prediction(gllim)
    # exp.mesures.plot_retrouveY(gllim,[0.01,0.08,2,4])
    exp.mesures.illustration(gllim, x, y)

    #  Xtest, Ytest , errs = exp.mesures.plot_modal_prediction(gllim,[0.00001])
    # print(errs)
    # n = errs[0][1]
    # Y0 = Ytest[n:n+1,:]
    # X0 = Xtest[n]
    # print(X0)
    # exp.mesures.plot_conditionnal_density(gllim,Y0,X0_obs=X0,dim=1,colorplot=True)

def test_hapke_vect():
    h= HapkeGonio1468(None)
    X = h.get_X_sampling(10000)
    GX = h._genere_data_for_Hapke(X)
    t = time.time()
    y1 = Hapke_vect(*GX)
    print("Hapke time ", time.time() - t)
    t = time.time()
    y2 = Hapke_opt(*GX)
    print("Hapke opt time ", time.time() - t)
    assert np.allclose(y1, y2)

def test_map():
    h = VoieS(None)
    Y , mask = h.get_observations_fixed_wl(wave_index=0)
    latlong = h.get_spatial_coord()[mask]
    mask2 = [not np.allclose(x,0) for x in latlong]
    latlong = latlong[mask2]
    graphiques.map_values(latlong, np.ones(len(latlong)))

def test_dF():
    c = HapkeContext(partiel=(0,1))
    # graphiques.illustre_derivative(c.F, c.dF)

    x0 = np.array([[0.2,25]])
    eps = 0.0000000001
    h = np.array([10,-1])
    y = (c.F( x0 + eps * h ) - c.F(x0) )/ eps
    print(y[0] - c.dF(x0).dot(h))



def cA():
    exp = SecondLearning(HapkeContext)
    exp.load_data(regenere_data=False,with_noise=50,N=100000)
    X,Y = exp.Xtrain,exp.Ytrain
    g = dGLLiM(300)
    dGLLiM.dF_hook = exp.context.dF
    g.init_fit(X,Y,None)
    g2 = GLLiM(300)
    g2.init_fit(X,Y,None)
    return g, g2 ,X, Y


def evolu_cluster():
    exp = SecondLearning(HapkeContext, partiel=(0, 1), verbose=True)
    exp.load_data(regenere_data=False,with_noise=50,N=10000)
    # exp.NB_MAX_ITER = 200
    dGLLiM.dF_hook = exp.context.dF
    gllim = exp.load_model(300, mode="l", track_theta=True, init_local=500,
                           gamma_type=""
                                      "full", gllim_cls=dGLLiM)
    thetas, LLs = exp.archive.load_tracked_thetas()
    # exp.mesures.evolution1D(thetas)
    exp.mesures.evolution_clusters2D(thetas)


def setup_jGLLiM_GLLiM():
    X = np.random.multivariate_normal(np.zeros(5) + 0.2, np.eye(5), 100000)
    Y = np.random.multivariate_normal(np.zeros(6) + 10, np.eye(6), 100000)

    gllim = GLLiM(100, 0, sigma_type="full", gamma_type="full", verbose=None)
    gllim.init_fit(X, Y, None)

    jgllim = jGLLiM(100, 0, sigma_type="full", gamma_type="full", verbose=None)
    jgllim.init_fit(X, Y, None)

    return gllim, jgllim, X, Y


def equivalence_jGLLiM_GLLIM():
    X = np.random.multivariate_normal(np.zeros(5) + 0.2, np.eye(5), 2000)
    Y = np.random.multivariate_normal(np.zeros(6) + 10, np.eye(6), 2000)

    gllim = GLLiM(10, 0, sigma_type="full", gamma_type="full", verbose=True)
    gllim.fit(X, Y, None, maxIter=100)

    jgllim = jGLLiM(10, 0, sigma_type="full", gamma_type="full", verbose=True)
    jgllim.fit(X, Y, None, maxIter=99)

    theta = (gllim.pikList, gllim.ckList, gllim.GammakList, gllim.AkList, gllim.bkList, gllim.full_SigmakList)
    jtheta = (jgllim.pikList, jgllim.ckList, jgllim.GammakList, jgllim.AkList, jgllim.bkList, jgllim.full_SigmakList)

    is_egal(theta, jtheta)


def details_convergence(imax, RETRAIN):
    exp = Experience(InjectiveFunction(2))
    K_progression = np.arange(imax) * 3 + 2
    coeffNK = 10
    N_progression = K_progression * coeffNK
    filename = "/scratch/WORK/tmp_KN.mat"
    if RETRAIN:
        r = _train_K_N(exp, N_progression, K_progression,
                       with_null_sigma=True)
        l1, l2 = r.transpose(1, 0, 2)
        scipy.io.savemat(filename, {"l1": l1, "l2": l2})
    else:
        m = scipy.io.loadmat(filename)
        l1, l2 = m["l1"], m["l2"]

    labels = np.array(Mesures.LABELS_STUDY_ERROR)
    choix = [0, 1, 2, 3, 4]
    labels = labels[choix]
    labels2 = [x + " - 0-$\Sigma$" for x in labels]
    labels = [l for l1, l2 in zip(labels, labels2) for l in [l1, l2]]
    data = l1.T[choix]
    data2 = l2.T[choix]
    data = np.array([v for d1, d2 in zip(data, data2) for v in [d1, d2]])
    data = np.array(data <= 1000, dtype=float) * data + np.array(data > 1000, dtype=int)
    title = "Evolution de l'erreur en fonction de K et N"
    xlabels = K_progression
    graphiques.doubleplusieursKN(data, labels, xlabels, True, "K", "Erreur", savepath="../evoKN.png",
                                 title=title, write_context=False)




if __name__ == '__main__':
    coloredlogs.install(level=logging.DEBUG, fmt="%(module)s %(asctime)s : %(levelname)s : %(message)s",
                        datefmt="%H:%M:%S")
    # cA()
    # graphiques.plot_Y(Y)qw
    # simple_function()
    # evolu_cluster()
    # equivalence_jGLLiM_GLLIM()  # OK
    # test_dF()
    # _compare_Fsym()   #OK 27 /6 /2018
    # test_map()
    # plusieurs_K_N(False,imax=200,Nfixed=False,Kfixed=False)
    # compare_R(sigma_type="full",gamma_type="iso")
    details_convergence(60, True)
