
import os
os.environ["CHAINER_SEED"] = "1234"

import random
import numpy as np
random.seed(1234)
np.random.seed(1234)

import chainer
from chainer import cuda
from chainer import optimizers
import chainer.functions as F

from bi_lstm import BiLSTM

import util
from util import PADDING, UNKWORD


import logging
logger = logging.getLogger(__name__)

to_cpu = chainer.cuda.to_cpu
import os.path


def train(train_file, **args):
    batchsize = args['batchsize']
    model_name = args['model_name']
    optimizer_name = args['optimizer']
    save_dir = args['save_dir']
    print args
    if save_dir[-1] != '/':
        save_dir = save_dir + '/'

    # TODO: check save_dir exist
    if not os.path.isdir(save_dir):
        err_msg = 'There is no dir : {}\n'.format(save_dir)
        err_msg += '##############################\n'
        err_msg += '## Please followiing: \n'
        err_msg += '## $ mkdir {}\n'.format(save_dir)
        err_msg += '##############################\n'
        raise ValueError(err_msg)

    save_name = args['save_name']
    if save_name == '':
        save_name = '_'.join([model_name, optimizer_name])

    save_name = save_dir + save_name

    xp = cuda.cupy if args['gpu'] >= 0 else np
    if args['gpu'] >= 0:
        cuda.get_device(args['gpu']).use()
        xp.random.seed(1234)

    # load files
    dev_file = args['dev_file']
    test_file = args['test_file']
    delimiter = args['delimiter']
    sentences_train = util.read_conll_file(filename=train_file,
                                           delimiter=delimiter,
                                           input_idx=0, output_idx=-1)
    if len(sentences_train) == 0:
        s = str(len(sentences_train))
        err_msg = 'Invalid training sizes: {} sentences. '.format(s)
        raise ValueError(err_msg)

    sentences_train = sentences_train[:100]

    sentences_dev = []
    sentences_test = []
    if dev_file:
        sentences_dev = util.read_conll_file(dev_file, delimiter=delimiter,
                                             input_idx=0, output_idx=-1)
    if test_file:
        sentences_test = util.read_conll_file(test_file, delimiter=delimiter,
                                              input_idx=0, output_idx=-1)

    # TODO: check unkown pos tags
    # TODO: compute unk words
    sentences_words_train = [w_obj[0] for w_obj in sentences_train]
    vocab = util.build_vocab(sentences_words_train)
    vocab_char = util.build_vocab(util.flatten(sentences_words_train))
    vocab_tags = util.build_tag_vocab(sentences_train)

    PAD_IDX = vocab[PADDING]
    UNK_IDX = vocab[UNKWORD]

    def parse_to_word_ids(sentences):
        x_data = [xp.array([vocab.get(w[0].lower(), UNK_IDX)
                            for w in sentence], dtype=xp.int32)
                  for sentence in sentences]
        return x_data

    def parse_to_char_ids(sentences):
        x_data = [[xp.array([vocab_char.get(c, UNK_IDX) for c in w[0]],
                            dtype=xp.int32)
                   for w in sentence]
                  for sentence in sentences]
        return x_data

    def parse_to_tag_ids(sentences):
        x_data = [xp.array([vocab_tags.get(w[-1], -1)
                            for w in sentence], dtype=xp.int32)
                  for sentence in sentences]
        return x_data

    x_train = parse_to_word_ids(sentences_train)
    x_char_train = parse_to_char_ids(sentences_train)
    y_train = parse_to_tag_ids(sentences_train)

    x_dev = parse_to_word_ids(sentences_dev)
    x_char_dev = parse_to_char_ids(sentences_dev)
    y_dev = parse_to_tag_ids(sentences_dev)

    x_test = parse_to_word_ids(sentences_test)
    x_char_test = parse_to_char_ids(sentences_test)
    y_test = parse_to_tag_ids(sentences_test)

    cnt_train_unk = sum([xp.sum(d == UNK_IDX) for d in x_train])
    cnt_train_word = sum([d.size for d in x_train])
    unk_train_unk_rate = float(cnt_train_unk) / cnt_train_word

    cnt_dev_unk = sum([xp.sum(d == UNK_IDX) for d in x_dev])
    cnt_dev_word = sum([d.size for d in x_dev])
    unk_dev_unk_rate = float(cnt_dev_unk) / max(cnt_dev_word, 1)

    logging.info('train:' + str(len(x_train)))
    logging.info('dev  :' + str(len(x_dev)))
    logging.info('test :' + str(len(x_test)))
    logging.info('vocab     :' + str(len(vocab)))
    logging.info('vocab_tags:' + str(len(vocab_tags)))
    logging.info('unk count (train):' + str(cnt_train_unk))
    logging.info('unk rate  (train):' + str(unk_train_unk_rate))
    logging.info('cnt all words (train):' + str(cnt_train_word))
    logging.info('unk count (dev):' + str(cnt_dev_unk))
    logging.info('unk rate  (dev):' + str(unk_dev_unk_rate))
    logging.info('cnt all words (dev):' + str(cnt_dev_word))
    # show model config
    logging.info('######################')
    logging.info('## Model Config')
    logging.info('model_name:' + str(model_name))
    logging.info('batchsize:' + str(batchsize))
    logging.info('optimizer:' + str(optimizer_name))
    # Save model config
    logging.info('######################')
    logging.info('## Model Save Config')
    logging.info('save_dir :' + str(save_dir))

    # save vocab
    save_vocab = save_name + '.vocab'
    save_vocab_char = save_name + '.vocab_char'
    save_tags_vocab = save_name + '.vocab_tag'
    save_train_config = save_name + '.train_config'
    logging.info('save_vocab        :' + save_vocab)
    logging.info('save_vocab_char   :' + save_vocab_char)
    logging.info('save_tags_vocab   :' + save_tags_vocab)
    logging.info('save_train_config :' + save_train_config)
    util.write_vocab(save_vocab, vocab)
    util.write_vocab(save_vocab_char, vocab_char)
    util.write_vocab(save_tags_vocab, vocab_tags)
    util.write_vocab(save_train_config, args)

    net = BiLSTM(n_vocab=len(vocab), n_char_vocab=len(vocab_char),
                 emb_dim=args['n_word_emb'],
                 hidden_dim=args['n_hidden'],
                 n_layers=args['n_layer'], init_emb=None,
                 n_label=len(vocab_tags))

    if args['word_emb_file']:
        # set Pre-trained embeddings
        # emb_file = './emb/glove.6B.100d.txt'
        emb_file = args['word_emb_file']
        word_ids, word_vecs = util.load_glove_embedding(emb_file, vocab)
        net.word_embed.W.data[word_ids] = word_vecs

    if args['gpu'] >= 0:
        net.to_gpu()

    init_alpha = args['init_lr']
    if optimizer_name == 'adam':
        opt = optimizers.Adam(alpha=init_alpha, beta1=0.9, beta2=0.9)
    elif optimizer_name == 'adadelta':
        opt = optimizers.AdaDelta()
    if optimizer_name == 'sgd_mom':
        opt = optimizers.MomentumSGD(lr=init_alpha, momentum=0.9)
    if optimizer_name == 'sgd':
        opt = optimizers.SGD(lr=init_alpha)

    opt.setup(net)
    opt.add_hook(chainer.optimizer.GradientClipping(5.0))
    tmax = args['max_iter']
    t = 0.0
    for epoch in xrange(args['max_iter']):

        # train
        net.set_train(train=True)
        iteration_list = range(0, len(x_train), batchsize)
        perm = np.random.permutation(len(x_train))
        sum_loss = 0.0
        predict_train = []
        for i_index, index in enumerate(iteration_list):
            data = [(x_train[i], x_char_train[i], y_train[i])
                    for i in perm[index:index + batchsize]]
            x, x_char, target_y = zip(*data)

            output = net(x_data=x, x_char_data=x_char)
            predict, loss = net.predict(output, target_y)

            # loss
            sum_loss += loss.data

            # update
            net.zerograds()
            loss.backward()
            opt.update()

            predict_train.extend(predict)

        # Evaluation
        train_accuracy = util.eval_accuracy(predict_train)

        logging.info('epoch:' + str(epoch))
        logging.info(' [train]')
        logging.info('  loss     :' + str(sum_loss))
        logging.info('  accuracy :' + str(train_accuracy))
        logging.info('  alpha    :' + str(opt.alpha))

        def eval_loop(x_data, x_char_data, y_data):
            # dev
            net.set_train(train=False)
            iteration_list = range(0, len(x_data), batchsize)
            perm = np.random.permutation(len(x_data))
            sum_loss = 0.0
            predict_lists = []
            for i_index, index in enumerate(iteration_list):
                data = [(x_data[i], x_char_data[i], y_data[i])
                        for i in perm[index:index + batchsize]]
                x, x_char, target_y = zip(*data)

                output = net(x_data=x, x_char_data=x_char)
                predict, loss = net.predict(output, target_y)

                sum_loss += loss.data
                predict_lists.extend(predict)
            return predict_lists, sum_loss

        predict_dev, loss_dev = eval_loop(x_dev, x_char_dev, y_dev)

        # Evaluation
        dev_accuracy = util.eval_accuracy(predict_dev)
        logging.info(' [dev]')
        logging.info('  loss     :' + str(loss_dev))
        logging.info('  accuracy :' + str(dev_accuracy))
