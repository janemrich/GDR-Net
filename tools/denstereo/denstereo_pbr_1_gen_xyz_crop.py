from __future__ import division, print_function

import os

os.environ["PYOPENGL_PLATFORM"] = "egl"
import os.path as osp
import sys

import mmcv
import numpy as np
from tqdm import tqdm

cur_dir = osp.abspath(osp.dirname(__file__))
PROJ_ROOT = osp.join(cur_dir, "../..")
sys.path.insert(0, PROJ_ROOT)
from lib.meshrenderer.meshrenderer_phong import Renderer
from lib.vis_utils.image import grid_show
from lib.pysixd import misc
from lib.utils.mask_utils import mask2bbox_xyxy


idx2class = {
    1: "002_master_chef_can",  # [1.3360, -0.5000, 3.5105]
    2: "003_cracker_box",  # [0.5575, 1.7005, 4.8050]
    3: "004_sugar_box",  # [-0.9520, 1.4670, 4.3645]
    4: "005_tomato_soup_can",  # [-0.0240, -1.5270, 8.4035]
    5: "006_mustard_bottle",  # [1.2995, 2.4870, -11.8290]
    6: "007_tuna_fish_can",  # [-0.1565, 0.1150, 4.2625]
    7: "008_pudding_box",  # [1.1645, -4.2015, 3.1190]
    8: "009_gelatin_box",  # [1.4460, -0.5915, 3.6085]
    9: "010_potted_meat_can",  # [2.4195, 0.3075, 8.0715]
    10: "011_banana",  # [-18.6730, 12.1915, -1.4635]
    11: "019_pitcher_base",  # [5.3370, 5.8855, 25.6115]
    12: "021_bleach_cleanser",  # [4.9290, -2.4800, -13.2920]
    13: "024_bowl",  # [-0.2270, 0.7950, -2.9675]
    14: "025_mug",  # [-8.4675, -0.6995, -1.6145]
    15: "035_power_drill",  # [9.0710, 20.9360, -2.1190]
    16: "036_wood_block",  # [1.4265, -2.5305, 17.1890]
    17: "037_scissors",  # [7.0535, -28.1320, 0.0420]
    18: "040_large_marker",  # [0.0460, -2.1040, 0.3500]
    19: "051_large_clamp",  # [10.5180, -1.9640, -0.4745]
    20: "052_extra_large_clamp",  # [-0.3950, -10.4130, 0.1620]
    21: "061_foam_brick",  # [-0.0805, 0.0805, -8.2435]
}

class2idx = {_name: _id for _id, _name in idx2class.items()}

classes = idx2class.values()
classes = sorted(classes)

# DEPTH_FACTOR = 1000.
IM_H = 480
IM_W = 640
near = 0.01
far = 6.5

data_dir = osp.normpath(osp.join(PROJ_ROOT, "datasets/BOP_DATASETS/"))

cls_indexes = sorted(idx2class.keys())
cls_names = [idx2class[cls_idx] for cls_idx in cls_indexes]
#model_dir = osp.normpath(osp.join(PROJ_ROOT, "datasets/BOP_DATASETS/denstereo/models"))
model_dir = osp.normpath("/home/jemrich/datasets/BOP_DATASETS/denstereo/models")
model_paths = [osp.join(model_dir, f"obj_{obj_id:06d}.ply") for obj_id in cls_indexes]
texture_paths = None

scenes = [i for i in range(0, 49 + 1)]

K = np.array([[1066.7779541015625, 0.0, 312.98690807819366], [0.0, 1067.4870531406486, 241.31089784012457], [0.0, 0.0, 1.0]]) # denstereo pbr cam

def normalize_to_01(img):
    if img.max() != img.min():
        return (img - img.min()) / (img.max() - img.min())
    else:
        return img


def get_emb_show(bbox_emb):
    show_emb = bbox_emb.copy()
    show_emb = normalize_to_01(show_emb)
    return show_emb


class XyzGen(object):
    def __init__(self, dataset="denstereo-test", split="train", scene="all"):
        if split == "train" or "train_pbr_right" or "train_pbr_left":
            scene_ids = scenes
            data_root = osp.normpath(osp.join(data_dir, dataset, split))
        else:
            raise ValueError(f"split {split} error")

        if scene == "all":
            sel_scene_ids = scene_ids
        else:
            assert int(scene) in scene_ids, f"{scene} not in {scene_ids}"
            sel_scene_ids = [int(scene)]
        print("split: ", split, "selected scene ids: ", sel_scene_ids)
        self.split = split
        self.scene = scene
        self.sel_scene_ids = sel_scene_ids
        self.data_root = data_root
        self.renderer = None
        self.xyz_root = osp.join(PROJ_ROOT, "datasets/BOP_DATASETS", dataset, split, "xyz_crop")

    def get_renderer(self):
        if self.renderer is None:
            self.renderer = Renderer(
                model_paths, vertex_tmp_store_folder=osp.join(PROJ_ROOT, ".cache"), vertex_scale=0.001
            )
        return self.renderer

    def main(self):
        split = self.split
        scene = self.scene  # "all" or a single scene
        sel_scene_ids = self.sel_scene_ids
        data_root = self.data_root

        for scene_id in tqdm(sel_scene_ids, postfix=f"{split}_{scene}"):
            print("split: {} scene: {}".format(split, scene_id))
            scene_root = osp.join(data_root, f"{scene_id:06d}")

            gt_dict = mmcv.load(osp.join(scene_root, "scene_gt.json"))
            # gt_info_dict = mmcv.load(osp.join(scene_root, "scene_gt_info.json"))
            # cam_dict = mmcv.load(osp.join(scene_root, "scene_camera.json"))

            for str_im_id in tqdm(gt_dict, postfix=f"{scene_id}"):
                int_im_id = int(str_im_id)

                for anno_i, anno in enumerate(gt_dict[str_im_id]):
                    obj_id = anno["obj_id"]
                    if obj_id not in idx2class:
                        continue

                    R = np.array(anno["cam_R_m2c"], dtype="float32").reshape(3, 3)
                    t = np.array(anno["cam_t_m2c"], dtype="float32") / 1000.0
                    # pose = np.hstack([R, t.reshape(3, 1)])

                    save_path = osp.join(
                        self.xyz_root,
                        f"{scene_id:06d}/{int_im_id:06d}_{anno_i:06d}-xyz.pkl",
                    )
                    if osp.exists(save_path) and osp.getsize(save_path) > 0:
                        continue

                    render_obj_id = cls_indexes.index(obj_id)  # 0-based
                    bgr_gl, depth_gl = self.get_renderer().render(render_obj_id, IM_W, IM_H, K, R, t, near, far)
                    mask = (depth_gl > 0).astype("uint8")

                    if mask.sum() == 0:  # NOTE: this should be ignored at training phase
                        print(
                            f"not visible, split {split} scene {scene_id}, im {int_im_id} obj {idx2class[obj_id]} {obj_id}"
                        )
                        print(f"{save_path}")
                        xyz_info = {
                            "xyz_crop": np.zeros((IM_H, IM_W, 3), dtype=np.float16),
                            "xyxy": [0, 0, IM_W - 1, IM_H - 1],
                        }
                        if VIS:
                            im_path = osp.join(
                                data_root,
                                f"{scene_id:06d}/rgb/{int_im_id:06d}.jpg",
                            )
                            im = mmcv.imread(im_path)

                            mask_path = osp.join(
                                data_root,
                                f"{scene_id:06d}/mask/{int_im_id:06d}_{anno_i:06d}.png",
                            )
                            mask_visib_path = osp.join(
                                data_root,
                                f"{scene_id:06d}/mask_visib/{int_im_id:06d}_{anno_i:06d}.png",
                            )
                            mask_gt = mmcv.imread(mask_path, "unchanged")
                            mask_visib_gt = mmcv.imread(mask_visib_path, "unchanged")

                            show_ims = [
                                bgr_gl[:, :, [2, 1, 0]],
                                im[:, :, [2, 1, 0]],
                                mask_gt,
                                mask_visib_gt,
                            ]
                            show_titles = [
                                "bgr_gl",
                                "im",
                                "mask_gt",
                                "mask_visib_gt",
                            ]
                            grid_show(show_ims, show_titles, row=2, col=2)
                            raise RuntimeError(f"split {split} scene {scene_id}, im {int_im_id}")
                    else:
                        x1, y1, x2, y2 = mask2bbox_xyxy(mask)
                        xyz_np = misc.calc_xyz_bp_fast(depth_gl, R, t, K)
                        xyz_crop = xyz_np[y1 : y2 + 1, x1 : x2 + 1]
                        xyz_info = {
                            "xyz_crop": xyz_crop.astype("float16"),  # save disk space w/o performance drop
                            "xyxy": [x1, y1, x2, y2],
                        }

                        if VIS:
                            print(f"xyz_crop min {xyz_crop.min()} max {xyz_crop.max()}")
                            show_ims = [
                                bgr_gl[:, :, [2, 1, 0]],
                                get_emb_show(xyz_np),
                                get_emb_show(xyz_crop),
                            ]
                            show_titles = ["bgr_gl", "xyz", "xyz_crop"]
                            grid_show(show_ims, show_titles, row=1, col=3)

                    if not args.no_save:
                        mmcv.mkdir_or_exist(osp.dirname(save_path))
                        mmcv.dump(xyz_info, save_path)
        if self.renderer is not None:
            self.renderer.close()


if __name__ == "__main__":
    import argparse
    import time

    import setproctitle

    parser = argparse.ArgumentParser(description="gen lm train_pbr xyz")
    parser.add_argument("--dataset", type=str, default="denstereo-test", help="dataset")
    parser.add_argument("--split", type=str, default="train_pbr_left", help="split")
    parser.add_argument("--scene", type=str, default="all", help="scene id")
    parser.add_argument("--num_scenes", type=int, default=1, help="num of scene id")
    parser.add_argument("--vis", default=False, action="store_true", help="vis")
    parser.add_argument("--no-save", default=False, action="store_true", help="do not save results")
    args = parser.parse_args()

    height = IM_H
    width = IM_W

    VIS = args.vis

    if args.num_scenes > 1:
        for scene in range(int(args.scene), args.num_scenes):
            T_begin = time.perf_counter()
            setproctitle.setproctitle(f"gen_xyz_lm_train_pbr_{args.dataset}_{args.split}_{args.scene}")
            xyz_gen = XyzGen(args.dataset, args.split, scene)
            xyz_gen.main()
            T_end = time.perf_counter() - T_begin
            print("dataset", args.dataset, "split", args.split, "scene", args.scene, "total time: ", T_end)
    else:
        T_begin = time.perf_counter()
        setproctitle.setproctitle(f"gen_xyz_lm_train_pbr_{args.dataset}_{args.split}_{args.scene}")
        xyz_gen = XyzGen(args.dataset, args.split, args.scene)
        xyz_gen.main()
        T_end = time.perf_counter() - T_begin
        print("dataset", args.dataset, "split", args.split, "scene", args.scene, "total time: ", T_end)
