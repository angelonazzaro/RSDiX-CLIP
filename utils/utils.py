import json
import os
from typing import Tuple

import torch.cuda
import xmltodict


# https://math.stackexchange.com/questions/102978/incremental-computation-of-standard-deviation
def inc_var(value: float, n: int = 1, prev_var: float = 0.0, prev_mean: float = 0.0) -> float:
    if n == 1:
        return 0.0
    return (n - 2)/(n - 1) * prev_var + 1 / n * (value - prev_mean)**2


def get_splits(n_instances: int, train_split_percentage: float, val_split_percentage: float) -> Tuple[int, int, int]:
    """
    Calculate dataset splits based on specified percentages.

    Args:
        n_instances (int): Total number of instances.
        train_split_percentage (float): Percentage of instances for the training split.
        val_split_percentage (float): Percentage of instances for the validation split.

    Returns:
        Tuple[int, int, int]: Number of instances for training, validation, and test splits.
    """

    if train_split_percentage == 0 and val_split_percentage == 0:
        return 0, 0, n_instances

    train_split = int(n_instances * train_split_percentage / 100)
    remaining_split = n_instances - train_split
    val_split = int(n_instances * val_split_percentage / 100)
    test_split = remaining_split - val_split

    # If no test set is required, then test_split is just remainder, that we can add to the train
    if train_split_percentage + val_split_percentage >= 100.0:
        train_split = train_split + test_split
        test_split = 0

    return train_split, val_split, test_split


def s2lcd_to_json(annotations_file: str, json_file_name: str = "dataset_s2lcd"):
    """
    Convert S2LCD dataset annotations from XML to JSON format.

    Args:
        annotations_file (str): Path to the XML annotations file.
        json_file_name (str): Name of the output JSON file.
    """
    with open(annotations_file) as f:
        data_dict = xmltodict.parse(f.read())

    data_dict = data_dict["annotations"]
    images = {"images": []}

    for image in data_dict["image"]:
        image_data = {"filename": image["@name"], "imgid": int(image["@id"])}
        sentences = []
        for mask in image["mask"]:
            sentences.append({"raw": mask["@label"]})
        image_data["sentences"] = sentences
        images["images"].append(image_data)

    # get annotations_file directory
    data_dir = os.path.dirname(annotations_file)
    with open(f"{data_dir}/{json_file_name}.json", "w") as f:
        json.dump(images, f, indent=4)


def separate_rsicd_test_images(annotations_file: str, test_output_file: str = "dataset_rsicd_test.json"):
    """
    Separate test images from RSICD dataset and create a separate JSON file for test images.

    Args:
        annotations_file (str): Path to the JSON annotations file.
        test_output_file (str): Name of the output JSON file for test images.
    """
    data = []
    with open(annotations_file) as json_file:
        for line in json_file:
            data.append(json.loads(line))
    test_images = {"images": [], "dataset": data["dataset"]}
    new_data = {"images": [], "dataset": data["dataset"]}

    for idx, img in enumerate(data["images"]):
        if img["split"] == "test":
            test_images["images"].append(img)
        else:
            new_data["images"].append(img)

    # overwrite existing dataset
    with open(annotations_file, "w") as json_file:
        json.dump(new_data, json_file)

    with open(test_output_file, "w") as json_file:
        json.dump(test_images, json_file)


def separate_nwpu_test_images(annotations_file: str, test_output_file: str = "dataset_nwpu_test.json"):
    """
        Separate test images from NWPU-Captions dataset and create a separate JSON file for test images.

        Args:
            annotations_file (str): Path to the JSON annotations file.
            test_output_file (str): Name of the output JSON file for test images.
    """
    data = []
    with open(annotations_file, encoding="utf8") as json_file:
        data = json.load(json_file)

    train_data = {"images": [], "dataset": "NWPU-Captions"}
    test_data = {"images": [], "dataset": "NWPU-Captions"}

    # the dataset is structure as follows:
    # category:
    #   [
    #       "filename": "category_1",
    #       "split": "train",
    #       "raw": "raw sentence 1",
    #       "raw_1": "raw sentence 2",
    #       ...
    #   ]
    for category in data.keys():
        for category_row in data[category]:
            row = {
                "filename": f"{category}{os.sep}{category_row['filename']}",
                "imgid": category_row["imgid"],
                "split": category_row["split"],
                "sentences": [{"raw": category_row[raw_key]} for raw_key in category_row.keys() if
                              raw_key.startswith("raw")]
            }
            if row["split"] == "test":
                test_data["images"].append(row)
            else:
                train_data["images"].append(row)

        # overwrite existing dataset
    with open(annotations_file, "w") as json_file:
        json.dump(train_data, json_file)

    with open(test_output_file, "w") as json_file:
        json.dump(test_data, json_file)


def enable_matmul_precision(precision: str = "high"):
    if not torch.cuda.is_available():
        return

    num_gpus = torch.cuda.device_count()

    for gpu_id in range(num_gpus):
        gpu_properties = torch.cuda.get_device_properties(gpu_id)

        # Check if the GPU supports Tensor Cores (CUDA capability >= 7)
        if gpu_properties.major >= 7:
            torch.cuda.set_device(gpu_id)
            torch.set_float32_matmul_precision(precision)


def load_model_checkpoint(model_class, checkpoint_path: str):
    try:
        if os.path.exists(checkpoint_path):
            model = model_class.load_from_checkpoint(checkpoint_path, strict=False)

            return model.to(torch.device('cuda')) if torch.cuda.is_available() and model.device.type == "cpu" else model
        else:
            raise Exception(f"checkpoint file: '{checkpoint_path}' does not exist.")
    except FileNotFoundError:
        # Since Lightning saves the checkpoint with the current OS file separator, in case of OS switching,
        # if the checkpoint being loaded was instantiated with a valid "checkpoint_path", the FileNotFoundError
        # exception will be raised
        ckpt = torch.load(checkpoint_path)

        # instantiate model to remain coherent with the checkpoint
        # ignoring the "checkpoint" arguments since they are causing the issue
        hyper_parameters = {key: value for key, value in ckpt["hyper_parameters"].items() if "checkpoint" not in key}
        model = model_class(**hyper_parameters)

        # load state dict
        model.load_state_dict(ckpt["state_dict"])

        return model.to(torch.device('cuda')) if torch.cuda.is_available() and model.device.type == "cpu" else model


class ListWrapper(list):
    """
    A custom list class that supports device assignment.
    """

    def __init__(self, initial_list=None):
        """
        Initialize the ListWrapper

        Args:
            initial_list (list): Initial list to populate the object.
        """
        if initial_list is None:
            super().__init__()
        else:
            super().__init__(initial_list)

        self._device = "cuda" if torch.cuda.is_available() else "cpu"

    @property
    def device(self):
        return self._device

    @device.setter
    def device(self, device):
        self._device = device

    def to(self, device):
        self._device = device
        return self
