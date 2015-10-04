# coding: utf-8
#
# Copyright 2015 The Oppia Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import copy
import operator
import pickle

import numpy


class StringClassifier(object):
    """Handles math-y internals for classifying strings.
    https://en.wikipedia.org/wiki/Latent_Dirichlet_allocation"""

    # Learning rates
    _DEFAULT_ALPHA = 0.1
    _DEFAULT_BETA = 0.001

    def __init__(self):
        """
        Hieroglyph decoder:
        b - boolean
        c - count
        i - id
        l - label
        w - word
        d - doc

        Internal (private) model representation:
        _w_dc - word (id) given doc and count
            (list of word ids which represent a doc)
        _b_dl - boolean given doc and label
            (boolean of whether a doc has a label)
        _l_dc - label given doc and count
            (assigned label of each word in a doc)
        _c_dl - count given doc and label
            (count of each label per doc)
        _c_lw - count given label and word
            (count of labels per word)
        _c_l - count given label (count of each label)
        """
        # Ensure that results are deterministic
        # There is nothing special about the value 4
        numpy.random.seed(seed=4)

        self._alpha = self._DEFAULT_ALPHA
        self._beta = self._DEFAULT_BETA

    def _get_word_id(self, word):
        """Returns a word's id if it exists, otherwise assigns
        a new id to the word and returns it."""
        try:
            return self._word_to_id[word]
        except KeyError as ke:
            self._word_to_id[word] = self._word_count
            self._word_count += 1
        return self._word_to_id[word]

    def _get_label_id(self, label):
        """Returns a word's id if it exists, otherwise assigns
        a new id to the label and returns it."""
        try:
            return self._label_to_id[label]
        except KeyError as ke:
            self._label_to_id[label] = self._label_count
            self._label_count += 1
        return self._label_to_id[label]

    def _get_record(self, d):
        """Given a doc id, return the doc and labels."""
        return self._w_dc[d], self._b_dl[d]

    def _get_label_vector(self, labels):
        """Returns a vector specifying which labels
        are specified in the training set."""
        if len(labels) == 0:
            return numpy.ones(self._label_count)
        label_vector = numpy.zeros(self._label_count)
        for label in labels:
            label_vector[self._get_label_id(label)] = 1
        # Always set default label
        label_vector[self._label_to_id['_default']] = 1
        return label_vector

    def _update_counting_matrices(self, d, w, l, val):
        """Update counting matrices given doc/word/label indices."""
        self._c_dl[d, l] += val
        self._c_lw[l, w] += val
        self._c_l[l] += val

    def _get_doc_ids(self, doc_ids):
        if doc_ids is None:
            doc_ids = xrange(self._doc_count)
        return doc_ids

    def _init_docs(self, doc_ids=None):
        """Initialize data for given docs (defaults to all)."""
        doc_ids = self._get_doc_ids(doc_ids)

        for d in doc_ids:
            doc, labels = self._get_record(d)
            l_c = [
                numpy.random.multinomial(1, labels / labels.sum()).argmax()
                for i in xrange(len(doc))
            ]
            self._l_dc.append(l_c)
            for w, l in zip(doc, l_c):
                self._update_counting_matrices(d, w, l, 1)

    def _infer_docs(self, doc_ids):
        """Runs iterative inference on given docs (default all)."""
        doc_ids = self._get_doc_ids(doc_ids)

        statez = {
            'updates': 0,
            'computes': 0
        }

        for d in doc_ids:
            doc, labels = self._get_record(d)
            for c in xrange(len(doc)):
                w = doc[c]
                l = self._l_dc[d][c]

                self._update_counting_matrices(d, w, l, -1)

                # Gibbs update of labels
                coeff_a = 1 / (
                    self._c_dl[d].sum() + self._label_count * self._alpha)
                coeff_b = 1 / (
                    self._c_lw.sum(axis=1) + self._word_count * self._beta)
                prob_l = (
                    labels *
                    coeff_a * (self._c_dl[d] + self._alpha) *
                    coeff_b * (self._c_lw[:, w] + self._beta)
                )
                new_l = numpy.random.multinomial(
                    1, prob_l / prob_l.sum()
                    ).argmax()

                statez['computes'] += 1
                if l != new_l:
                    statez['updates'] += 1

                self._l_dc[d][c] = new_l
                self._update_counting_matrices(d, w, new_l, 1)

        return statez

    def _get_probabilities(self, d):
        """Returns the probability of a document having a label."""
        probs_i = self._c_dl[d] + (self._b_dl[d] * self._alpha)
        probs_i = probs_i / probs_i.sum(axis=0)[numpy.newaxis]
        return probs_i

    def _get_probabilities_with_label(self, d):
        """Includes human readable labels with document probabilities."""
        probs_i = self._get_probabilities(d)
        probs_l = {}
        for label, l in self._label_to_id.iteritems():
            probs_l[label] = probs_i[l]
        return probs_l

    def _predict(self, d, threshold=0.5):
        """Calculates prediction data for a doc"""
        probs_l = self._get_probabilities_with_label(d)
        default_prob = probs_l['_default']
        for l in sorted(probs_l, key=probs_l.get, reverse=True):
            prob_l = probs_l[l]
            if l != '_default' and prob_l / (1 - default_prob) > threshold:
                return l, prob_l / (1 - default_prob), probs_l
        return '_default', default_prob / (1 - default_prob), probs_l

    def _parse_examples(self, examples):
        """Splits examples into docs (split on spaces) and labels."""
        docs = []
        labels = []
        for example in examples:
            doc = example[0].split()
            if len(doc) > 0:
                docs.append(doc)
                labels.append(example[1])
        return docs, labels

    def _train_docs(self, iterations=25, doc_ids=None):
        """Trains given docs (default all) for a number of iterations."""
        doc_ids = self._get_doc_ids(doc_ids)

        for i in xrange(iterations):
            statez = self._infer_docs(doc_ids)

    def load_examples(self, examples, iterations=25):
        """Sets new examples. Overwrites existing ones."""
        docs, labels = self._parse_examples(examples)

        label_set = set(
            ['_default'] +
            [label for label_list in labels for label in label_list]
        )

        self._label_count = len(label_set)
        self._label_to_id = dict(zip(label_set, xrange(self._label_count)))

        self._word_count = 0
        self._word_to_id = {}

        self._doc_count = len(docs)

        self._b_dl = numpy.array(
            map(self._get_label_vector, labels), dtype=int)
        self._w_dc = [map(self._get_word_id, doc) for doc in docs]
        self._l_dc = []
        self._c_dl = numpy.zeros(
            (self._doc_count, self._label_count), dtype=int)
        self._c_lw = numpy.zeros(
            (self._label_count, self._word_count), dtype=int)
        self._c_l = numpy.zeros(self._label_count, dtype=int)

        self._init_docs()
        self._train_docs(iterations)

    def add_examples(self, examples, iterations=5):
        """Adds examples. Old examples are preserved."""
        docs, labels = self._parse_examples(examples)

        last_label_count = self._label_count
        last_doc_count = self._doc_count
        last_word_count = self._word_count

        [map(self._get_label_id, label_list) for label_list in labels]
        self._doc_count += len(docs)

        self._b_dl = numpy.concatenate(
            (self._b_dl, numpy.zeros(
                (last_doc_count, self._label_count - last_label_count),
                dtype=int)), axis=1)
        self._b_dl = numpy.concatenate(
            (
                self._b_dl,
                [self._get_label_vector(label_list) for label_list in labels]
            ),
            axis=0)
        self._w_dc.extend([map(self._get_word_id, doc) for doc in docs])
        self._c_dl = numpy.concatenate(
            (self._c_dl, numpy.zeros(
                (last_doc_count, self._label_count - last_label_count),
                dtype=int)), axis=1)
        self._c_dl = numpy.concatenate(
            (self._c_dl, numpy.zeros(
                (self._doc_count - last_doc_count, self._label_count),
                dtype=int)), axis=0)
        self._c_lw = numpy.concatenate(
            (self._c_lw, numpy.zeros(
                (last_label_count, self._word_count - last_word_count),
                dtype=int)), axis=1)
        self._c_lw = numpy.concatenate(
            (self._c_lw, numpy.zeros(
                (self._label_count - last_label_count, self._word_count),
                dtype=int)), axis=0)
        self._c_l = numpy.concatenate(
            (self._c_l, numpy.zeros(
                self._label_count - last_label_count, dtype=int)))

        for d in xrange(last_doc_count, self._doc_count):
            self._init_docs([d])
            self._train_docs(iterations, [d])

        return xrange(last_doc_count, self._doc_count)

    def predict_label(self, d, threshold=0.5):
        """Calculates predicted label for a doc."""
        return self._predict(d, threshold)[0]

    def to_dict(self):
        """Converts a classifier into a dict model."""
        model = {}
        model['_alpha'] = copy.deepcopy(self._alpha)
        model['_beta'] = copy.deepcopy(self._beta)
        model['_label_count'] = copy.deepcopy(self._label_count)
        model['_doc_count'] = copy.deepcopy(self._doc_count)
        model['_word_count'] = copy.deepcopy(self._word_count)
        model['_label_to_id'] = copy.deepcopy(self._label_to_id)
        model['_word_to_id'] = copy.deepcopy(self._word_to_id)
        model['_w_dc'] = copy.deepcopy(self._w_dc)
        model['_b_dl'] = copy.deepcopy(self._b_dl)
        model['_l_dc'] = copy.deepcopy(self._l_dc)
        model['_c_dl'] = copy.deepcopy(self._c_dl)
        model['_c_lw'] = copy.deepcopy(self._c_lw)
        model['_c_l'] = copy.deepcopy(self._c_l)
        return model

    def from_dict(self, model):
        """Converts a dict model into a classifier."""
        self._alpha = copy.deepcopy(model['_alpha'])
        self._beta = copy.deepcopy(model['_beta'])
        self._label_count = copy.deepcopy(model['_label_count'])
        self._doc_count = copy.deepcopy(model['_doc_count'])
        self._word_count = copy.deepcopy(model['_word_count'])
        self._label_to_id = copy.deepcopy(model['_label_to_id'])
        self._word_to_id = copy.deepcopy(model['_word_to_id'])
        self._w_dc = copy.deepcopy(model['_w_dc'])
        self._b_dl = copy.deepcopy(model['_b_dl'])
        self._l_dc = copy.deepcopy(model['_l_dc'])
        self._c_dl = copy.deepcopy(model['_c_dl'])
        self._c_lw = copy.deepcopy(model['_c_lw'])
        self._c_l = copy.deepcopy(model['_c_l'])
