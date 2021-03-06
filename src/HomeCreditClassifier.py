from sklearn.metrics import roc_auc_score
from copy import deepcopy
from math import floor
import numpy as np
import time
import gc


class KFoldClassifier:
    def __init__(self, clf, cv, feat_sample=1, sample_seed=0):
        self.__clfs = [deepcopy(clf) for i in range(cv.n_splits)]
        self.__cv = cv
        self.__kfold_result = {}
        self.__feat_sample_rate = feat_sample
        self.__seed = sample_seed

    def __feat_sample(self, cols):
        np.random.seed(self.__seed)
        if self.__feat_sample_rate < 1:
            np.random.shuffle(cols)
            x = floor(len(cols) * self.__feat_sample_rate)
            return cols[:x]
        else:
            return cols

    def __fit_on_one_fold(self, X, y, on, **kwargs):
        """
        train One model using one specific fold in cv.
        on - indicate which fold the model is training on, start from 0.
        """
        clf = self.__clfs[on]
        t0 = time.time()
        clf.fit(X, y, **kwargs)
        t1 = time.time()
        fold_result = {}
        fold_result['using_time'] = t1 - t0
        fold_result['feature_importance'] = clf.feature_importances_

        fold_result['best_iteration'] = clf.best_iteration_

        fold_result['best_score'] = {}
        fold_result['best_score']['training'] = clf.best_score_[
            'training']['auc']
        fold_result['best_score']['valid'] = clf.best_score_[
            'valid_1']['auc']

        fold_result['evals_result'] = {}
        fold_result['evals_result']['training'] = clf.evals_result_[
            'training']['auc']
        fold_result['evals_result']['valid'] = clf.evals_result_[
            'valid_1']['auc']

        self.__kfold_result['fold_%s' % (on + 1)] = fold_result

    def __predict_proba_out_of_fold(self, X, out, **kwargs):
        """
        predict the probability using the data out of one specific fold in cv.
        out - indicate out of which fold the model is making predictions,
        start from 0.
        """
        clf = self.__clfs[out]
        return clf.predict_proba(X, num_iteration=clf.best_iteration_, **kwargs)[:, 1]

    def predict_proba(self, X, **kwargs):
        """
        predict probability when all the models are trained.
        """
        X = X[self.__features]
        ret = np.zeros(X.shape[0])
        for clf in self.__clfs:
            ret += clf.predict_proba(X,
                                     num_iteration=clf.best_iteration_, **kwargs)[:, 1]
        ret /= len(self.__clfs)
        return ret

    def fit(self, X, y, **kwargs):
        oof_preds = np.zeros(X.shape[0])
        self.__features = self.__feat_sample(list(X.columns))
        X = X[self.__features]

        for n_fold, (train_idx, valid_idx) in enumerate(self.__cv.split(X, y)):
            train_x, train_y = X.iloc[train_idx], y.iloc[train_idx]
            valid_x, valid_y = X.iloc[valid_idx], y.iloc[valid_idx]

            self.__fit_on_one_fold(train_x, train_y, on=n_fold,
                                   eval_set=[(train_x, train_y),
                                             (valid_x, valid_y)],
                                   eval_metric='auc', verbose=100,
                                   early_stopping_rounds=500)
            oof_preds[valid_idx] = self.__predict_proba_out_of_fold(
                valid_x, out=n_fold)
            valid_auc = self.__kfold_result['fold_%s' % (
                n_fold + 1)]['best_score']['valid']
            print('Fold %2d AUC : %.6f.' % (n_fold + 1, valid_auc))
            del train_x, train_y, valid_x, valid_y
            gc.collect()

        full_auc = roc_auc_score(y, oof_preds)
        print('Full AUC score %.6f.' % full_auc)
        self.__score = full_auc
        self.__oof_preds = oof_preds

    @property
    def score_(self):
        """
        the full AUC score
        """
        return self.__score

    @property
    def features_(self):
        return self.__features

    @property
    def classifiers_(self):
        return self.__clfs

    @property
    def kfold_result_(self):
        return self.__kfold_result

    @property
    def oof_preds_(self):
        return self.__oof_preds


class StackingClassifier:
    def __init__(self, base_classifiers: dict, meta_classifier):
        self.__base_classifiers = []
        for name, clf in base_classifiers.items():
            self.__base_classifiers.append(clf)
            self.__base_classifiers[-1].name_ = name

        self.__meta_classifier = meta_classifier

    def __gen_new_X_fit(self, X, y):
        n_rows = X.shape[0]
        n_cols = len(self.__base_classifiers)
        ret = np.zeros((n_rows, n_cols))

        for i, clf in enumerate(self.__base_classifiers):
            print('Train on base classifier - %s.' % clf.name_)
            print('=' * 60)
            clf.fit(X, y)
            print('\n')
            ret[:, i] = clf.oof_preds_

        return ret

    def __gen_new_X_pred(self, X):
        n_rows = X.shape[0]
        n_cols = len(self.__base_classifiers)
        ret = np.zeros((n_rows, n_cols))
        for i, clf in enumerate(self.__base_classifiers):
            ret[:, i] = clf.predict_proba(X)
        return ret

    def predict_proba(self, X):
        new_X = self.__gen_new_X_pred(X)
        self.__new_X_pred = new_X
        return self.__meta_classifier.predict_proba(new_X)[:, 1]

    def fit(self, X, y):
        new_X = self.__gen_new_X_fit(X, y)
        self.__newX_fit = new_X
        print('Train meta classifier.')
        self.__meta_classifier.fit(new_X, y)
        return self.__meta_classifier

    @property
    def base_classifiers_(self):
        return self.__base_classifiers

    @property
    def meta_classifier_(self):
        return self.__meta_classifier
