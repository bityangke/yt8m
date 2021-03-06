import h5py
import threading
import cPickle as pkl
import random
import numpy as np
import Queue

import tensorflow as tf
from tensorflow.python.training import queue_runner
from . import feeding_queue_runner as fqr


class Feed_fn_setup(object):
  def __init__(self, num_classes):
    with open("/data/state/linchao/YT/video_hdfs/train/mean.pkl") as fin:
      vid_list = pkl.load(fin)
      self.vid_dict = {}
      for i, vid in enumerate(vid_list):
        self.vid_dict[vid] = i
    self.mean_data = h5py.File("/data/state/linchao/YT/video_hdfs/train/mean.h5", 'r', driver='core')['feas']

    print("loading vid info")
    with open("/data/uts700/linchao/yt8m/YT/data/vid_info/train_vid_to_labels_-1.pkl") as fin:
      self.vid_to_labels = pkl.load(fin)

    self.label_to_vid_dict = {}
    for vid, labels in self.vid_to_labels.iteritems():
      for l in labels:
        l = int(l)
        c = self.label_to_vid_dict.get(l, [])
        c.append(vid)
        self.label_to_vid_dict[l] = c

    self.num_classes = num_classes
    self.batch_size = 32

    self.batch_id_queue = Queue.Queue(1500)
    bi_threads = threading.Thread(target=self.input_vid_threads)
    bi_threads.start()


  def input_vid_threads(self):
    labels = np.arange(self.num_classes)

    label_vid_ptr = {}
    for i in xrange(self.num_classes):
      label_vid_ptr[i] = 0

    # step_size = num_classes / batch_size
    # batch_labels = classes[step_size * i: step_size * (i + 1)]
    batch_vids = []
    while True:
      np.random.shuffle(labels)
      for label in labels:
        vids = self.label_to_vid_dict[label]
        vid_ptr = label_vid_ptr[label]
        trav_cnt = 0
        while vids[vid_ptr] in batch_vids:
          if len(vids) == vid_ptr + 1:
            vid_ptr = 0
          else:
            vid_ptr += 1
          trav_cnt += 1
          if trav_cnt == 100:
            break
        if trav_cnt == 100:
          continue
        batch_vids.append(vids[vid_ptr])
        if len(batch_vids) == self.batch_size:
          self.batch_id_queue.put(batch_vids)
          batch_vids = []

        if len(vids) == vid_ptr + 1:
          label_vid_ptr[label] = 0
          random.shuffle(self.label_to_vid_dict[label])
        else:
          label_vid_ptr[label] = vid_ptr + 1


class Feed_fn(object):
  def __init__(self, info, placeholders):
    self._i = info
    self.vid_dict = info.vid_dict
    self.vid_to_labels = info.vid_to_labels
    self.placeholders = placeholders

  def __call__(self):
    vids = self._i.batch_id_queue.get()
    vid_index = []
    dense_labels = np.zeros((len(vids), self._i.num_classes), dtype=np.int64)
    for vid_idx, vid in enumerate(vids):
      idx = self.vid_dict[vid]
      vid_index.append(idx)
      labels = self.vid_to_labels[vid]
      for l in labels:
        dense_labels[vid_idx, int(l)] = 1

    vid_index = np.array(vid_index)
    vid_index_sortidx = np.argsort(vid_index)
    batch_data = self._i.mean_data[vid_index[vid_index_sortidx], :]
    batch_data = batch_data[np.argsort(vid_index_sortidx), :]

    vals = [np.array(vids), dense_labels, batch_data]
    feed_dict = {}
    for pl, val in zip(self.placeholders, vals):
      feed_dict[pl.name] = val
    return feed_dict

def enqueue_data(batch_size, num_classes, feature_size, name="enqueue_input",):
  fn_setup = Feed_fn_setup(num_classes)
  queue_types = [tf.string, tf.int64, tf.float32]
  queue_shapes = [(), (num_classes,), (feature_size,)]
  capacity = 1500
  num_threads = 8
  with tf.name_scope(name):
    queue = tf.FIFOQueue(capacity,
                         dtypes=queue_types,
                         shapes=queue_shapes)

    enqueue_ops = []
    feed_fns = []

    def return_identity(placeholders):
      return placeholders

    for i in range(num_threads):
      # Note the placeholders have no shapes, so they will accept any
      # enqueue_size.  enqueue_many below will break them up.
      placeholders = [tf.placeholder(t) for t in queue_types]
      out_ops = return_identity(placeholders)

      enqueue_ops.append(queue.enqueue_many(out_ops))
      feed_fns.append(Feed_fn(fn_setup, placeholders))

    runner = fqr.FeedingQueueRunner(queue=queue,
                                    enqueue_ops=enqueue_ops,
                                    feed_fns=feed_fns)
    queue_runner.add_queue_runner(runner)

    features = queue.dequeue_many(batch_size)
  return features
