# ----------------------------------------------------------------------------
# Copyright 2015 Nervana Systems Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ----------------------------------------------------------------------------
import numpy as np
import re

from neon import NervanaObject
from neon.data.datasets import load_babi
from neon.data.text import Text


class QA(NervanaObject):
    """
    A general QA container to take Q&A dataset, which has already been
    vectorized and create a data iterator to feed data to training
    """
    def __init__(self, story, query, answer):
        self.story, self.query, self.answer = story, query, answer
        self.ndata = len(self.story)
        self.nbatches = self.ndata/self.be.bsz
        self.story_length = self.story.shape[1]
        self.query_length = self.query.shape[1]
        self.shape = [(self.story_length, 1), (self.query_length, 1)]

    def __iter__(self):
        """
        Generator that can be used to iterate over this dataset.

        Yields:
            tuple : the next minibatch of data.
        """
        self.batch_index = 0
        shuf_idx = self.be.rng.permutation(len(self.story))
        self.story = self.story[shuf_idx]
        self.query = self.query[shuf_idx]
        self.answer = self.answer[shuf_idx]

        while self.batch_index < self.nbatches:
            batch = slice(self.batch_index*self.be.bsz, (self.batch_index+1)*self.be.bsz)
            story_tensor = self.be.array(self.story[batch].T.copy())
            query_tensor = self.be.array(self.query[batch].T.copy())
            answer_tensor = self.be.array(self.answer[batch].T.copy())

            self.batch_index += 1

            yield (story_tensor, query_tensor), answer_tensor

    def reset(self):
        """
        For resetting the starting index of this dataset back to zero.
        Relevant for when one wants to call repeated evaluations on the dataset
        but don't want to wrap around for the last uneven minibatch
        Not necessary when ndata is divisible by batch size
        """
        self.batch_index = 0


class BABI(NervanaObject):
    """
    This class loads in the Facebook bAbI dataset and vectorizes them into stories,
    questions, and answers as described in:
    "Towards AI-Complete Question Answering: A Set of Prerequisite Toy Tasks"
    http://arxiv.org/abs/1502.05698

    """
    def __init__(self, path='.', task='qa1_single-supporting-fact', subset='en'):
        """
        Load bAbI dataset and extract text and read the stories
        For a particular task, the class will read both train and test files
        and combine the vocabulary.

        Args:
            path (str): Directory to store the dataset
            task (str): a particular task to solve (all bAbI tasks are train
                        and tested separately)
            train (str): to load the train data or test data {'train', 'test'}
            subset (str): subset of the dataset to use: {en, en-10k, hn, hn-10k}
        """

        print 'Preparing bAbI dataset or extracting from %s' % path
        print 'Task is %s/%s' % (subset, task)
        self.tasks = [
            'qa1_single-supporting-fact',
            'qa2_two-supporting-facts',
            'qa3_three-supporting-facts',
            'qa4_two-arg-relations',
            'qa5_three-arg-relations',
            'qa6_yes-no-questions',
            'qa7_counting',
            'qa8_lists-sets',
            'qa9_simple-negation',
            'qa10_indefinite-knowledge',
            'qa11_basic-coreference',
            'qa12_conjunction',
            'qa13_compound-coreference',
            'qa14_time-reasoning',
            'qa15_basic-deduction',
            'qa16_basic-induction',
            'qa17_positional-reasoning',
            'qa18_size-reasoning',
            'qa19_path-finding',
            'qa20_agents-motivations'
            ]
        assert task in self.tasks, "given task is not in the bAbI dataset"

        self.train_file, self.test_file = load_babi(path, task)
        self.train_parsed = BABI.parse_babi(self.train_file)
        self.test_parsed = BABI.parse_babi(self.test_file)

        self.compute_statistics()
        self.train = self.vectorize_stories(self.train_parsed)
        self.test = self.vectorize_stories(self.test_parsed)

    @staticmethod
    def data_to_list(data):
        """
        Clean a block of data and split into lines.

        Args:
            data (string) : String of bAbI data.

        Returns:
            list : List of cleaned lines of bAbI data.
        """
        split_lines = data.split('\n')[:-1]
        return [line.decode('utf-8').strip() for line in split_lines]

    @staticmethod
    def tokenize(sentence):
        """
        Split a sentence into tokens including punctuation.

        Args:
            sentence (string) : String of sentence to tokenize.

        Returns:
            list : List of tokens.
        """
        return [x.strip() for x in re.split('(\W+)?', sentence) if x.strip()]

    @staticmethod
    def flatten(data):
        """
        Flatten a list of data.

        Args:
            data (list) : List of list of words.

        Returns:
            list : A single flattened list of all words.
        """
        return reduce(lambda x, y: x + y, data)

    @staticmethod
    def parse_babi(babi_file):
        """
        Parse bAbI data into stories, queries, and answers.

        Args:
            babi_data (string) : String of bAbI data.

        Returns:
            list of tuples : List of (story, query, answer) words.
        """
        babi_data = open(babi_file).read()
        lines = BABI.data_to_list(babi_data)

        data, story = [], []
        for line in lines:
            nid, line = line.split(' ', 1)
            if int(nid) == 1:
                story = []
            if '\t' in line:
                q, a, supporting = line.split('\t')
                substory = [x for x in story if x]
                data.append((substory, BABI.tokenize(q), a))
                story.append('')
            else:
                sent = BABI.tokenize(line)
                story.append(sent)

        return [(BABI.flatten(_story), _question, answer) for _story, _question, answer in data]

    def words_to_vector(self, words):
        """
        Convert a list of words into vector form.

        Args:
            words (list) : List of words.

        Returns:
            list : Vectorized list of words.
        """
        return [self.word_to_index[w] if w in self.word_to_index
                else self.vocab_size - 1 for w in words]

    def one_hot_vector(self, answer):
        """
        Create one-hot representation of an answer.

        Args:
            answer (string) : The word answer.

        Returns:
            list : One-hot representation of answer.
        """
        vector = np.zeros(self.vocab_size)
        vector[self.word_to_index[answer]] = 1
        return vector

    def vectorize_stories(self, data):
        """
        Convert (story, query, answer) word data into vectors.

        Args:
            data (tuple) : Tuple of story, query, answer word data.

        Returns:
            tuple : Tuple of story, query, answer vectors.
        """
        s, q, a = [], [], []
        for story, query, answer in data:
            s.append(self.words_to_vector(story))
            q.append(self.words_to_vector(query))
            a.append(self.one_hot_vector(answer))

        s = Text.pad_sentences(s, self.story_maxlen)
        q = Text.pad_sentences(q, self.query_maxlen)
        a = np.array(a)
        return (s, q, a)

    def compute_statistics(self):
        """
        Compute vocab, word index, and max length of stories and queries
        """
        all_data = self.train_parsed + self.test_parsed
        vocab = sorted(reduce(lambda x, y: x | y, (set(s + q + [a]) for s, q, a in all_data)))
        self.vocab = vocab
        # Reserve 0 for masking via pad_sequences and self.vocab_size - 1 for <UNK> token
        self.vocab_size = len(vocab) + 2
        self.word_to_index = dict((c, i + 1) for i, c in enumerate(vocab))
        self.index_to_word = dict((i + 1, c) for i, c in enumerate(vocab))
        self.story_maxlen = max(map(len, (s for s, _, _ in all_data)))
        self.query_maxlen = max(map(len, (q for _, q, _ in all_data)))
