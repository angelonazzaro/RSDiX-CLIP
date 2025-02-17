import os
from argparse import ArgumentParser

from lightning.pytorch.trainer import Trainer
from lightning.pytorch.tuner import Tuner

from datasets import CaptioningDataModule
from models import RSDiXClip, RSDiXClipCap
from utils import enable_matmul_precision


def main(args):
    # suppress hugging face tokenizers warning
    if args.num_workers > 1:
        os.environ["TOKENIZERS_PARALLELISM"] = '1'

    model = RSDiXClip() if args.finetune_clipcap is False else RSDiXClipCap(prefix_length=args.prefix_length)
    datamodule = CaptioningDataModule(annotations_files=args.annotations_files, img_dirs=args.img_dirs,
                                      batch_size=args.batch_size, num_workers=args.num_workers,
                                      use_gpt2_tokenizer=args.finetune_clipcap)
    trainer = Trainer(default_root_dir=args.default_root_dir, max_epochs=5, log_every_n_steps=1)

    tuner = Tuner(trainer)

    # finds learning rate automatically
    # sets hparams.lr or hparams.learning_rate to that learning rate
    # Pick point based on plot, or get suggestion
    lr_finder = tuner.lr_find(model, datamodule=datamodule,
                              attr_name="lr" if args.finetune_clipcap is False else "clipcap_lr",
                              early_stop_threshold=None)
    optimal_lr = lr_finder.suggestion()

    # save to  file
    with open(f"{args.results_file}", "w") as f:
        f.write(f"optimal_lr: {optimal_lr}\n")


if __name__ == "__main__":
    parser = ArgumentParser()

    parser.add_argument("--default_root_dir", type=str,
                        default=os.path.join(os.getcwd(), "lightning_logs/tuner_checkpoints"),
                        help="Trainer's default root dir. The directory where the tuner's checkpoints will be saved")
    parser.add_argument("--results_file", type=str, default="results.txt",
                        help="File where tuner's results will be saved")
    parser.add_argument("--annotations_files", nargs='*',
                        default=["./data/RSICD/dataset_rsicd.json", "./data/UCMD/dataset_ucmd.json",
                                 "./data/RSITMD/dataset_rsitmd.json",
                                 "./data/S2LCD/dataset_s2lcd.json", "./data/NWPU-Captions/dataset_nwpu.json"])
    parser.add_argument("--img_dirs", nargs='*',
                        default=["./data/RSICD/RSICD_images", "./data/UCMD/UCMD_images", "./data/RSITMD/RSITMD_images",
                                 "./data/S2LCD/S2LCD_images", "./data/NWPU-Captions/NWPU-Captions_images"])
    parser.add_argument("--num_workers", type=int, default=0)
    parser.add_argument("--batch_size", type=int, default=2)
    parser.add_argument("--finetune_clipcap", default=False, action="store_true")
    parser.add_argument("--prefix_length", type=int, default=40)

    enable_matmul_precision()
    main(parser.parse_args())
