import os
import dask.array as da
import numpy as np
from sklearn.decomposition import PCA
import seaborn as sns
import argparse
import h5py
from tqdm import tqdm
from tpot import TPOTRegressor, TPOTClassifier
from torch import nn, optim
import torch
from torch.nn import functional as F
from torch.utils import data
from torch.autograd import Variable
import sklearn
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline, make_union
from sklearn.preprocessing import RobustScaler, StandardScaler
from tpot.builtins import StackingEstimator, ZeroCount
from sklearn.decomposition import LatentDirichletAllocation as LDA


class ECoG_NN(nn.Module):
    def __init__(self, in_features, transfer_func):
        super(ECoG_NN, self).__init__()
        self.hidden_list = []
        self.hidden_list.append(nn.Linear(in_features, 1000))
        self.hidden_list.append(nn.Linear(1000, 2000))
        # self.hidden_list.append(nn.Linear(2000, 4000))
        # self.hidden_list.append(nn.Linear(4000, 8000))
        # self.hidden_list.append(nn.Linear(8000, 4000))
        # self.hidden_list.append(nn.Linear(4000, 2000))
        self.hidden_list.append(nn.Linear(2000, 1000))
        self.hidden_list.append(nn.Linear(1000, 50))
        self.hidden_list.append(nn.Linear(50, 1))

        self.hidden_list = nn.ModuleList(self.hidden_list)

        self.transfer_func = transfer_func

    def forward(self, x):
        for layer in self.hidden_list:
            x = self.transfer_func(layer(x))

        return x


def make_all_data(all_data, labels):
    # y = [0 for x in zeros]
    # y.extend([1 for x in ones])
    # all_data = da.concatenate([zeros, ones]).compute()
    all_data = all_data.reshape(all_data.shape[0],
                                all_data.shape[1] * all_data.shape[2])
    all_data = np.nan_to_num(all_data)
    labels = np.nan_to_num(labels)

    return all_data, labels


def run_tpot(zeros, ones):
    all_data, y = make_all_data(zeros, ones)
    X_train, X_test, y_train, y_test = train_test_split(
        all_data, y, test_size=.1)
    pca = PCA(n_components=15)
    X_train = pca.fit_transform(X_train)
    X_test = pca.fit_transform(X_test)

    # if not os.path.exists('tpot_checkpoint'):
    # os.mkdir('tpot_checkpoint')

    tpot = TPOTClassifier(
        n_jobs=-1,
        generations=50,
        verbosity=3,
        scoring='f1',
        # subsample=.5,
        # periodic_checkpoint_folder='tpot_checkpoint',
        max_eval_time_mins=30,
        memory='auto')

    tpot.fit(X_train, y_train)
    tpot.export('tpot_ecog_pipeline.py')
    results = tpot.predict(X_test)
    out_file = open('tpot_metrics.txt', 'w')
    out_file.write(sklearn.metrics.classification_report(y_test, results))
    tpot.export('tpot_ecog_pipeline.py')


def pr_re(pred: np.ndarray, target: np.ndarray) -> tuple:
    tp = len([x for i, x in enumerate(pred) if x and target[i]])
    fp = len([x for i, x in enumerate(pred) if x and not target[i]])
    fn = len([x for i, x in enumerate(pred) if not x and target[i]])
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)

    return precision, recall


def run_nn(zeros, ones):
    num_epochs = 100
    all_data, y = make_all_data(zeros, ones)
    all_data = all_data.reshape(all_data.shape[0],
                                all_data.shape[1] * all_data.shape[2])
    pca = PCA(n_components=15)
    all_data = pca.fit_transform(all_data)
    X_train, X_test, y_train, y_test = train_test_split(
        all_data, y, stratify=y, test_size=.1)
    # X_train = pca.fit_transform(X_train)
    # X_test = pca.fit_transform(X_test)
    X_train = torch.from_numpy(X_train).float()
    X_test = torch.from_numpy(X_test).float()
    y_train = torch.Tensor(y_train).float()
    y_test = torch.Tensor(y_test).float()
    dataset = data.TensorDataset(X_train, y_train)
    loader = torch.utils.data.DataLoader(
        dataset, batch_size=10, shuffle=True, num_workers=0)
    model = ECoG_NN(X_train.shape[1], F.sigmoid).cuda()
    learning_rate = 1e-4
    opt = optim.SGD(model.parameters(), lr=learning_rate, momentum=.9)
    # sq_losses = []
    precision = []
    recall = []

    for epoch in range(num_epochs):
        for dataset in loader:
            train_y = Variable(dataset[1].float())
            train_x = Variable(dataset[0].float().cuda())
            train_y_hat = model(train_x).cpu()
            model.zero_grad()
            train_loss = F.mse_loss(train_y_hat, train_y).cpu()
            train_loss.backward()
            opt.step()
        # X_train = X_train.to("gpu")
        model = model.cpu()
        # all_train_y_hat = model(Variable(X_train))
        # X_train = X_train.to("cpu")
        # X_test = X_test.to("gpu")
        test_y_hat = model(Variable(X_test))
        # X_test = X_test.to("cpu")
        # all_train_loss = F.mse_loss(all_train_y_hat, Variable(y_train))
        # test_loss = F.mse_loss(test_y_hat, Variable(y_test))
        # all_train_loss = np.sum(
        #   all_train_y_hat.data.numpy()) / np.sum(y_train.numpy())
        # test_loss = np.sum(test_y_hat.data.numpy()) / np.sum(y_test.numpy())
        curr_precision, curr_recall = pr_re(test_y_hat.data.numpy(),
                                            y_test.numpy())
        precision.append(curr_precision)
        recall.append(curr_recall)
        # print(epoch, all_train_loss.data.numpy(), test_loss.data.numpy())
        # print(epoch, all_train_loss, test_loss)
        # sq_losses.append([all_train_loss, test_loss])
        model = model.cuda()
    torch.save(model, 'torch_nn')
    # train_errs = np.array([x[0].data.numpy() for x in sq_losses]).flatten()
    # test_errs = np.array([x[1].data.numpy() for x in sq_losses]).flatten()
    # sns_plot = sns.regplot(range(len(train_errs)), train_errs)
    # sns_plot.savefig("train_err")
    # sns_plot = sns.regplot(range(len(test_errs)), test_errs)
    # sns_plot.savefig("test_err")
    print(precision)
    print(recall)
    sns_plot = sns.regplot(
        np.array(list(range(len(precision))), int), precision)
    sns_plot.savefig("precision")
    sns_plot = sns.regplot(np.array(list(range(len(recall))), int), recall)
    sns_plot.savefig("recall")


def elbow_curve(data):
    data = data[1]
    data = data.reshape((data.shape[0], data.shape[1] * data.shape[2]))
    components = range(1, data.shape[1] + 1)
    explained_variance = []

    for component in tqdm(components[:50]):
        pca = PCA(n_components=component)
        pca.fit(data)
        explained_variance.append(sum(pca.explained_variance_ratio_))
    sns_plot = sns.regplot(
        x=np.array(components[:50]), y=explained_variance,
        fit_reg=False).get_figure()
    sns_plot.savefig("pca_elbow.png")


# def run_LDA(zeros, ones):
# all_data, labels = make_all_data(zeros, ones)
# lda = LDA(15)
# lda.fit(all_data)
# print(lda.get_params)


def get_data(data_loc: str) -> tuple:
    data_folders = [
        os.path.join(data_loc, x) for x in os.listdir(data_loc)
        if 'cb46fd46' in x
    ]
    out_data = None
    out_labels = None
    out_times = None

    for data_folder in tqdm(data_folders):
        all_data_fol = os.path.join(data_folder, 'data')
        label_folder = os.path.join(data_folder, 'labels')
        times_folder = os.path.join(data_folder, 'times')

        if out_data is None:
            out_data = da.from_npy_stack(all_data_fol)
        else:
            out_data = da.concatenate(
                [out_data, da.from_npy_stack(all_data_fol)])

        if out_labels is None:
            out_labels = da.from_npy_stack(label_folder)
        else:
            out_labels = da.concatenate(
                [out_labels, da.from_npy_stack(label_folder)])

        if out_times is None:
            out_times = da.from_npy_stack(times_folder)
        else:
            out_times = da.concatenate(
                [out_times, da.from_npy_stack(times_folder)])

    return out_data.compute(), out_labels.compute(), out_times.comput()


def get_data_loc() -> str:
    parser = argparse.ArgumentParser(prog='ecog_classifier')
    parser.add_argument('-d', required=True, help="Path to data")
    args = vars(parser.parse_args())
    DATA_LOC = args['d']

    return DATA_LOC


if __name__ == '__main__':
    DATA_LOC = get_data_loc()
    data, labels = get_data(DATA_LOC)
    # run_LDA(data, labels)
    run_tpot(data, labels)
    # run_nn(data, labels)
    # elbow_curve(get_data(DATA_LOC))
