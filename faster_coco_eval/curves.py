from .coco import COCO
from .cocoeval import COCOeval

from PIL import Image, ImageDraw
import pycocotools._mask as maskUtils
import numpy as np
import json
import time
import logging
from tqdm import tqdm
import os.path as osp

import matplotlib.pyplot as plt

try:
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go
    import plotly.express as px
    plotly_available = True
except:
    plotly_available = False

logger = logging.getLogger(__name__)


class Curves():
    A = 128
    DT_COLOR = (238, 130, 238, A)
    GT_COLOR = (0, 255, 0,   A)

    FN_COLOR = (255, 0, 0,   A)
    FP_COLOR = (0, 0, 255,   A)

    def __init__(self,
                 cocoGt: COCO = None,
                 cocoDt: COCO = None,
                 iouType: str = 'bbox',
                 min_score: float = 0,
                 iou_tresh: float = 0.0,
                 recall_count: int = 100,
                 useCats: bool = False,
                 ):
        self.iouType = iouType
        self.min_score = min_score
        self.iou_tresh = iou_tresh
        self.useCats = useCats

        self.cocoGt = cocoGt
        self.cocoDt = cocoDt

        cocoEval = COCOeval(self.cocoGt, self.cocoDt, iouType)
        cocoEval.params.maxDets = [len(cocoGt.anns)]

        cocoEval.params.iouThr = [0, 0.5]
        cocoEval.params.iouThrs = [iou_tresh]
        cocoEval.params.areaRng = [[0, 10000000000]]
        self.recThrs = np.linspace(0, 1, recall_count + 1, endpoint=True)
        cocoEval.params.recThrs = self.recThrs

        cocoEval.params.useCats = int(self.useCats)  # Выключение labels

        cocoEval.evaluate()
        cocoEval.accumulate()

        self.eval = cocoEval.eval
        self.math_matches()

    def math_matches(self):
        for gt_id, dt_id, is_tp in self.eval['matches']:
            is_tp = bool(is_tp)

            self.cocoDt.anns[dt_id]['tp'] = is_tp

            if is_tp:
                self.cocoGt.anns[gt_id]['tp'] = is_tp
                self.cocoGt.anns[gt_id]['dt_id'] = dt_id
                #
                self.cocoDt.anns[dt_id]['gt_id'] = gt_id

        for gt_id in self.cocoGt.anns.keys():
            if self.cocoGt.anns[gt_id].get('tp') is None:
                self.cocoGt.anns[gt_id]['fn'] = True

    def calc_auc(self, recall_list, precision_list):
        # https://towardsdatascience.com/how-to-efficiently-implement-area-under-precision-recall-curve-pr-auc-a85872fd7f14
        # mrec = np.concatenate(([0.], recall_list, [1.]))
        # mpre = np.concatenate(([0.], precision_list, [0.]))
        mrec = recall_list
        mpre = precision_list

        for i in range(mpre.size - 1, 0, -1):
            mpre[i - 1] = np.maximum(mpre[i - 1], mpre[i])

        i = np.where(mrec[1:] != mrec[:-1])[0]
        return np.sum((mrec[i + 1] - mrec[i]) * mpre[i + 1])

    def plot_pre_rec(self, plotly_backend=False, label="category_id"):
        use_plotly = False
        if plotly_backend:
            if plotly_available:
                fig = make_subplots(rows=1, cols=1, subplot_titles=[
                                    'Precision-Recall'])
                use_plotly = True
            else:
                logger.warning('plotly not instaled...')

        if not use_plotly:
            fig, axes = plt.subplots(ncols=1)
            fig.set_size_inches(15, 7)
            axes = [axes]

        output = {
            'auc': [],
        }

        if self.useCats:
            cat_ids = list(range(self.eval['precision'].shape[2]))
        else:
            cat_ids = [0]

        for category_id in cat_ids:
            _label = f"[{label}={category_id}] "
            if len(cat_ids) == 1:
                _label = ""

            precision_list = self.eval['precision'][:,
                                                    :, category_id, :, :].ravel()
            recall_list = self.recThrs

            scores = self.eval['scores'][:, :, category_id, :, :].ravel()

            auc = round(self.calc_auc(recall_list, precision_list), 4)

            if use_plotly:
                fig.add_trace(
                    go.Scatter(
                        x=recall_list,
                        y=precision_list,
                        name=f'{_label}auc: {auc:.3f}',
                        mode='lines',
                        text=scores,
                        hovertemplate='Pre: %{y:.3f}<br>' +
                        'Rec: %{x:.3f}<br>' +
                        'Score: %{text:.3f}<extra></extra>',
                        showlegend=True,
                    ),
                    row=1, col=1
                )
            else:
                axes[0].set_title('Precision-Recall')
                axes[0].set_xlabel('Recall')
                axes[0].set_ylabel('Precision')
                axes[0].plot(recall_list, precision_list,
                             label=f'{_label}auc: {auc:.3f}')
                axes[0].grid(True)
                axes[0].legend()

        if use_plotly:
            margin = 0.01
            fig.layout.yaxis.range = [0 - margin, 1 + margin]
            fig.layout.xaxis.range = [0 - margin, 1 + margin]

            fig.layout.yaxis.title = 'Precision'
            fig.layout.xaxis.title = 'Recall'

            fig.update_layout(height=600, width=1200)
            fig.show()
        else:
            plt.show()

    def draw_ann(self, draw, ann, color, width=5):
        if self.iouType == 'bbox':
            x1, y1, w, h = ann['bbox']
            draw.rectangle([x1, y1, x1+w, y1+h], outline=color, width=width)
        else:
            for poly in ann['segmentation']:
                if len(poly) > 3:
                    draw.polygon(poly, outline=color, width=width)

    def plot_img(self, img, force_matplot=False, figsize=None, slider=False):
        if plotly_available and not force_matplot:
            if not slider:
                fig = px.imshow(img)
            else:
                fig = px.imshow(img, animation_frame=0,
                                labels=dict(animation_frame="enum"))

            fig.update_layout(coloraxis_showscale=False)
            fig.update_layout(height=600, width=1200)
            fig.show()
        else:
            if figsize is not None:
                plt.figure(figsize=figsize)
            plt.imshow(img, interpolation='nearest')
            plt.axis('off')
            plt.show()

    def print_colors_info(self, _print=False):
        _print_func = logger.info
        if _print:
            _print_func = print

        if logger.getEffectiveLevel() <= 20 or _print:
            _print_func(f"DT_COLOR : {self.DT_COLOR}")
            im = Image.new("RGBA", (64, 32), self.DT_COLOR)
            self.plot_img(im, force_matplot=True, figsize=(1, 0.5))
            _print_func("")

            _print_func(f"GT_COLOR : {self.GT_COLOR}")
            im = Image.new("RGBA", (64, 32), self.GT_COLOR)
            self.plot_img(im, force_matplot=True, figsize=(1, 0.5))
            _print_func("")

            _print_func(f"FN_COLOR : {self.FN_COLOR}")
            im = Image.new("RGBA", (64, 32), self.FN_COLOR)
            self.plot_img(im, force_matplot=True, figsize=(1, 0.5))
            _print_func("")

            _print_func(f"FP_COLOR : {self.FP_COLOR}")
            im = Image.new("RGBA", (64, 32), self.FP_COLOR)
            self.plot_img(im, force_matplot=True, figsize=(1, 0.5))
            _print_func("")

    def display_tp_fp_fn(self, image_ids=['all'],
                         line_width=7,
                         display_fp=True,
                         display_fn=True,
                         display_tp=True,
                         resize_out_image=None,
                         data_folder=None,
                         ):
        image_batch = []

        for image_id, gt_anns in self.cocoGt.imgToAnns.items():
            if (image_id in image_ids) or 'all' in image_ids:
                image = self.cocoGt.imgs[image_id]

                if data_folder is not None:
                    image_fn = osp.join(data_folder, image["file_name"])
                else:
                    image_fn = image["file_name"]

                im = Image.open(image_fn)
                mask = Image.new("RGBA", im.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(mask)

                gt_anns = {ann['id']: ann for ann in gt_anns}
                if len(gt_anns) > 0:
                    for ann in gt_anns.values():
                        if ann.get('fn', False):
                            self.draw_ann(
                                draw, ann, color=self.FN_COLOR, width=line_width)

                dt_anns = self.cocoDt.imgToAnns[image_id]
                dt_anns = {ann['id']: ann for ann in dt_anns}

                if len(dt_anns) > 0:
                    for ann in dt_anns.values():
                        if ann.get('tp', False):
                            self.draw_ann(
                                draw, ann, color=self.DT_COLOR, width=line_width)
                            self.draw_ann(
                                draw, gt_anns[ann['gt_id']], color=self.GT_COLOR, width=line_width)
                        else:
                            self.draw_ann(
                                draw, ann, color=self.FP_COLOR, width=line_width)

                im.paste(mask, mask)
                image_batch.append(im)

        if len(image_batch) >= 1 and resize_out_image is None:
            resize_out_image = image_batch[0].size

        if len(image_batch) == 1:
            self.plot_img(image_batch[0].resize(resize_out_image))
        elif len(image_batch) > 1:
            image_batch = np.array([np.array(image.resize(resize_out_image))[
                                   :, :, ::-1] for image in image_batch])
            self.plot_img(image_batch, slider=True)

    def _compute_confusion_matrix(self, y_true, y_pred, fp={}, fn={}):
        """
        return classes*(classes + fp col + fn col)
        """
        categories_real_ids = list(self.cocoGt.cats)
        categories_enum_ids = {category_id: _i for _i,
                               category_id in enumerate(categories_real_ids)}
        K = len(categories_enum_ids)

        cm = np.zeros((K, K + 2), dtype=np.int32)
        for a, p in zip(y_true, y_pred):
            cm[categories_enum_ids[a]][categories_enum_ids[p]] += 1

        for enum_id, category_id in enumerate(categories_real_ids):
            cm[enum_id][-2] = fp.get(category_id, 0)
            cm[enum_id][-1] = fn.get(category_id, 0)

        return cm

    def compute_confusion_matrix(self):
        if self.useCats:
            logger.warning(
                f"The calculation may not be accurate. No intersection of classes. {self.useCats=}")

        y_true = []
        y_pred = []

        fn = {}
        fp = {}

        for image_id, gt_anns in self.cocoGt.imgToAnns.items():
            gt_anns = {ann['id']: ann for ann in gt_anns}
            if len(gt_anns) > 0:
                for ann in gt_anns.values():
                    if ann.get('fn', False):
                        if fn.get(ann['category_id']) is None:
                            fn[ann['category_id']] = 0

                        fn[ann['category_id']] += 1

            dt_anns = self.cocoDt.imgToAnns[image_id]
            dt_anns = {ann['id']: ann for ann in dt_anns}

            if len(dt_anns) > 0:
                for ann in dt_anns.values():
                    if ann.get('tp', False):
                        y_true.append(gt_anns[ann['gt_id']]['category_id'])
                        y_pred.append(ann['category_id'])
                    else:
                        if fp.get(ann['category_id']) is None:
                            fp[ann['category_id']] = 0

                        fp[ann['category_id']] += 1

        # classes fp fn
        cm = self._compute_confusion_matrix(y_true, y_pred, fp=fp, fn=fn)
        return cm

    def display_matrix(self, conf_matrix=None, in_percent=True, figsize=(10, 10), fontsize=16):
        if conf_matrix is None:
            conf_matrix = self.compute_confusion_matrix()

        names = [category['name']
                 for category_id, category in self.cocoGt.cats.items()]
        names += ['fp', 'fn']

        if in_percent:
            sum_by_col = conf_matrix.sum(axis=1)

        fig, ax = plt.subplots(figsize=figsize)
        ax.matshow(conf_matrix, cmap='Blues', alpha=0.3)
        for i in range(conf_matrix.shape[0]):
            for j in range(conf_matrix.shape[1]):

                value = conf_matrix[i, j]

                if in_percent:
                    value = int(value / sum_by_col[i] * 100)

                if value > 0:
                    ax.text(x=j, y=i, s=value, va='center', ha='center')

        plt.xlabel('Predictions', fontsize=fontsize)
        plt.ylabel('Actuals', fontsize=fontsize)

        plt.xticks(list(range(len(names))), names, rotation=90)
        plt.yticks(list(range(len(names[:-2]))), names[:-2])

        title = 'Confusion Matrix'
        if in_percent:
            title += ' [%]'

        plt.title(title, fontsize=fontsize)
        plt.show()
