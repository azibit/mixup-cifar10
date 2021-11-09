#!/usr/bin/env python3 -u
# Copyright (c) 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the LICENSE file in
# the root directory of this source tree.

#train.py --lr=0.1 --seed=20170922 --decay=1e-4 --epoch=2 --trials=2 --dataset_dir=../Datasets --iterations 2 -b for baseline
#train.py --lr=0.1 --seed=20170922 --decay=1e-4 --epoch=2 --trials=2 --dataset_dir=../Datasets --iterations 2 for mixup
from __future__ import print_function

import argparse
import csv
import os, sys, glob

import numpy as np
import torch
from torch.autograd import Variable
import torch.backends.cudnn as cudnn
import torch.nn as nn
import torch.optim as optim
import torchvision.transforms as transforms
import torchvision.datasets as datasets

import models
from utils import progress_bar, make_prediction

parser = argparse.ArgumentParser(description='PyTorch CIFAR10 Training')
parser.add_argument('--lr', default=0.1, type=float, help='learning rate')
parser.add_argument('--resume', '-r', action='store_true',
                    help='resume from checkpoint')
parser.add_argument('--model', default="ResNet18", type=str,
                    help='model type (default: ResNet18)')
parser.add_argument('--name', default='0', type=str, help='name of run')
parser.add_argument('--seed', default=0, type=int, help='random seed')
parser.add_argument('--batch-size', default=128, type=int, help='batch size')
parser.add_argument('--epoch', default=200, type=int,
                    help='total epochs to run')
parser.add_argument('--no-augment', dest='augment', action='store_false',
                    help='use standard augmentation (default: True)')
parser.add_argument('--decay', default=1e-4, type=float, help='weight decay')
parser.add_argument('--alpha', default=1., type=float,
                    help='mixup interpolation coefficient (default: 1)')
parser.add_argument('--dataset_dir', default='Data', type=str,
                    help='The location of the dataset to be explored')
parser.add_argument('--trials', default=5, type=int,
                    help='Number of times to run the complete experiment')
parser.add_argument('--baseline', '-b', action='store_true',
                    help='To run a baseline experiment without using Mixup')
parser.add_argument('--iterations', default=2, type=int,
                    help='Number of times to run the complete experiment')
args = parser.parse_args()

use_cuda = torch.cuda.is_available()

best_acc = 0  # best test accuracy
start_epoch = 0  # start from epoch 0 or last checkpoint epoch

torch.manual_seed(123)
if torch.cuda.is_available():
    torch.cuda.manual_seed(123)

if not os.path.exists(args.dataset_dir):
    file_utils.create_dir(args.dataset_dir)

dataset_list = sorted(glob.glob(args.dataset_dir + "/*"))
print("Dataset List: ", dataset_list)

if len(dataset_list) == 0:
    print("ERROR: 1. Add the Datasets to be run inside of the", args.dataset_dir, "folder")
    sys.exit()

# Data
print('==> Preparing data..')
if args.augment:
    transform_train = transforms.Compose([
        transforms.RandomCrop(32, padding=4),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize((0.4914, 0.4822, 0.4465),
                             (0.2023, 0.1994, 0.2010)),
    ])
else:
    transform_train = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.4914, 0.4822, 0.4465),
                             (0.2023, 0.1994, 0.2010)),
    ])


transform_test = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
])


def mixup_data(x, y, alpha=1.0, use_cuda=True):
    '''Returns mixed inputs, pairs of targets, and lambda'''
    if alpha > 0:
        lam = np.random.beta(alpha, alpha)
    else:
        lam = 1

    batch_size = x.size()[0]
    if use_cuda:
        index = torch.randperm(batch_size).cuda()
    else:
        index = torch.randperm(batch_size)

    mixed_x = lam * x + (1 - lam) * x[index, :]
    y_a, y_b = y, y[index]
    return mixed_x, y_a, y_b, lam


def mixup_criterion(criterion, pred, y_a, y_b, lam):
    return lam * criterion(pred, y_a) + (1 - lam) * criterion(pred, y_b)


def train(epoch):
    print('\nEpoch: %d' % epoch)
    net.train()
    train_loss = 0
    reg_loss = 0
    correct = 0
    total = 0
    for batch_idx, (inputs, targets) in enumerate(trainloader):
        if use_cuda:
            inputs, targets = inputs.cuda(), targets.cuda()

        print(args.baseline)
        if not args.baseline:
            inputs, targets_a, targets_b, lam = mixup_data(inputs, targets,
                                                       args.alpha, use_cuda)
        # Make Prediction
        outputs = net(inputs)

        if args.baseline:
            loss = criterion(outputs, targets)
            train_loss += loss.data.item()
            _, predicted = torch.max(outputs.data, 1)
            total += targets.size(0)
            correct += predicted.eq(targets.data).cpu().sum()

        else:
            loss = mixup_criterion(criterion, outputs, targets_a, targets_b, lam)
            train_loss += loss.data.item()
            _, predicted = torch.max(outputs.data, 1)
            total += targets.size(0)
            correct += (lam * predicted.eq(targets_a.data).cpu().sum().float()
                        + (1 - lam) * predicted.eq(targets_b.data).cpu().sum().float())

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        progress_bar(batch_idx, len(trainloader),
                     'Loss: %.3f | Reg: %.5f | Acc: %.3f%% (%d/%d)'
                     % (train_loss/(batch_idx+1), reg_loss/(batch_idx+1),
                        100.*correct/total, correct, total))
    return (train_loss/batch_idx, reg_loss/batch_idx, 100.*correct/total)


def test(epoch, loader):
    global best_acc
    net.eval()
    test_loss = 0
    correct = 0
    total = 0
    for batch_idx, (inputs, targets) in enumerate(loader):
        if use_cuda:
            inputs, targets = inputs.cuda(), targets.cuda()
        outputs = net(inputs)
        loss = criterion(outputs, targets)

        test_loss += loss.data[0]
        _, predicted = torch.max(outputs.data, 1)
        total += targets.size(0)
        correct += predicted.eq(targets.data).cpu().sum()

        progress_bar(batch_idx, len(testloader),
                     'Loss: %.3f | Acc: %.3f%% (%d/%d)'
                     % (test_loss/(batch_idx+1), 100.*correct/total,
                        correct, total))
    acc = 100.*correct/total
    if acc > best_acc:
        checkpoint(acc, epoch)
    if acc > best_acc:
        best_acc = acc
    return (test_loss/batch_idx, 100.*correct/total)


def checkpoint(acc, epoch):
    # Save checkpoint.
    print('Saving..')
    state = {
        'net': net,
        'acc': acc,
        'epoch': epoch,
        'rng_state': torch.get_rng_state()
    }
    if not os.path.isdir('checkpoint'):
        os.mkdir('checkpoint')
    torch.save(state, './checkpoint/ckpt.t7' + args.name + '_'
               + str(args.seed))


def adjust_learning_rate(optimizer, epoch):
    """decrease the learning rate at 100 and 150 epoch"""
    lr = args.lr
    if epoch >= 100:
        lr /= 10
    if epoch >= 150:
        lr /= 10
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr


for dataset in dataset_list:

    # 1. Location to save the output for the given dataset
    current_dataset_file = dataset.split("/")[-1] + '_.txt'

    for iteration in range(args.iterations):
        for trial in range(args.trials):

            print("Iteration", iteration, " Experiment: ", trial, "for dataset", dataset)

            trainset = datasets.ImageFolder(os.path.join(dataset, 'train'),
                                                      transform_train)
            trainloader = torch.utils.data.DataLoader(trainset,
                                                      batch_size=args.batch_size,
                                                      shuffle=True, num_workers=8)

            testset = datasets.ImageFolder(os.path.join(dataset, 'test'),
                                                      transform_test)
            testloader = torch.utils.data.DataLoader(testset, batch_size=100,
                                                     shuffle=False, num_workers=8)

            # Model
            if args.resume:
                # Load checkpoint.
                print('==> Resuming from checkpoint..')
                assert os.path.isdir('checkpoint'), 'Error: no checkpoint directory found!'
                checkpoint = torch.load('./checkpoint/ckpt.t7' + args.name + '_'
                                        + str(args.seed))
                net = checkpoint['net']
                best_acc = checkpoint['acc']
                start_epoch = checkpoint['epoch'] + 1
                rng_state = checkpoint['rng_state']
                torch.set_rng_state(rng_state)
            else:
                print('==> Building model..')
                net = models.__dict__[args.model](num_classes=len(class_names))

            results = "results_" + str(trial)
            if not os.path.isdir(results):
                os.mkdir(results)
            logname = (results + '/log_' + net.__class__.__name__ + '_' + args.name + '_'
                       + str(args.seed) + '.csv')


            if not os.path.exists(logname):
                with open(logname, 'w') as logfile:
                    logwriter = csv.writer(logfile, delimiter=',')
                    logwriter.writerow(['epoch', 'train loss', 'reg loss', 'train acc',
                                        'test loss', 'test acc'])

            if use_cuda:
                net.cuda()
                net = torch.nn.DataParallel(net)
                print(torch.cuda.device_count())
                cudnn.benchmark = True
                print('Using CUDA..')

            criterion = nn.CrossEntropyLoss()
            optimizer = optim.SGD(net.parameters(), lr=args.lr, momentum=0.9,
                                  weight_decay=args.decay)

            for epoch in range(start_epoch, args.epoch):
                train_loss, reg_loss, train_acc = train(epoch)
                test_loss, test_acc = test(epoch, testloader)

                adjust_learning_rate(optimizer, epoch)
                with open(logname, 'a') as logfile:
                    logwriter = csv.writer(logfile, delimiter=',')
                    logwriter.writerow([epoch, train_loss, reg_loss, train_acc, test_loss,
                                    test_acc])

                if epoch + 1 == args.epoch:
                    with open(current_dataset_file, 'a') as f:
                        print("Test result for iteration", iteration, "experiment:", trial, " for dataset ", dataset, file = f)
                        print(make_prediction(net, testset.classes, testloader, 'save'), file = f)
