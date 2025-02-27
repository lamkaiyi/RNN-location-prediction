# -*- coding: utf-8 -*-
"""RNN_location_prediction.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1xmQOdDsBHSYBFZt38YpLJmFfbohKeZF4
"""

import pandas as pd
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from torch.nn.utils.rnn import pad_sequence

import torch.nn as nn
import torch.optim as optim

import matplotlib.pyplot as plt
import argparse

seed = 4020

np.random.seed(seed)
torch.manual_seed(seed)
torch.cuda.manual_seed(seed)
torch.backends.cudnn.deterministic = True


## create argparse

def create_parser():
    """
    Creates and returns an argument parser object.
    
    Returns:
        argparse.ArgumentParser: Configured parser object.
    """
    parser = argparse.ArgumentParser(
        description="A sample parser for command-line arguments."
    )
    
    # Adding arguments
    parser.add_argument(
        '-i', '--input',
        type=str,
        required=True,
        help="Path to the input file."
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        required=False,
        default="/output",
        help="Path to the output folder (default: output.txt)."
    )
    
    return parser
   


class SequenceDataset(Dataset):
    def __init__(self, sequences, targets):
        self.sequences = sequences
        self.targets = targets

    def __len__(self):
        return len(self.sequences)

    def __getitem__(self, idx):
        return self.sequences[idx], self.targets[idx]


# Collate function to pad sequences in each batch
def collate_fn(batch):
    sequences, targets = zip(*batch)
    # Pad sequences to the max length in the batch
    padded_sequences = pad_sequence(sequences, batch_first=True) # pad before the start
    lengths = torch.tensor([len(seq) for seq in sequences], dtype=torch.int64)  # Get original lengths

    padded_targets = pad_sequence(targets, batch_first=True)  # (batch, max_seq_len, output_dim)
    return padded_sequences, padded_targets, lengths

def process_df(df, batch_size=32):

    """
    prepares each dataframe for training by loading it into a dataloader of the specified batchsize
    """

    df = df[df['uid']<=1000] # limit to first 1000 uid
    #df['coordinate_id'] = pd.factorize(list(zip(df['x'], df['y'])))[0] #encode into class labels

    sequences = (
        df.sort_values(by=['t'])  # Sort by 't' in ascending order
        .groupby(['uid', 'd'])  # Group by 'uid' and 'd'
        .apply(lambda group: list(zip(group['x'], group['y'])))  # Create list of (x, y) tuples
        .reset_index(name='coordinates')  # Reset index and give the aggregated column a name
)

    sequences['target'] = sequences['coordinates'].apply(lambda coords: coords[-1])  # Last  id
    sequences['coordinates'] = sequences['coordinates'].apply(lambda coords: coords[:-1])  # All except last

    sequences = sequences[(sequences['coordinates'].str.len() > 0)] # remove rows with no train data


    coordinates = sequences['coordinates'].apply(lambda seq: torch.tensor([(x, y) for x, y in seq], dtype=torch.float32))
    targets = sequences['target'].apply(lambda coord: torch.tensor(coord, dtype=torch.float32))

    dataset = SequenceDataset(coordinates.tolist(), torch.stack(targets.tolist()))
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True, collate_fn=collate_fn)

    return dataloader


class coordRNN(nn.Module):
  def __init__(self, in_d=2, out_d=2, hidden_d=4, num_hidden=1):
    super(coordRNN, self).__init__()
    self.num_layers = num_hidden
    self.hidden_size = hidden_d
    self.rnn = nn.RNN(input_size=in_d, hidden_size=hidden_d, num_layers=num_hidden, bidirectional=True)
    self.fc = nn.Linear(2 * hidden_d, out_d)

  def forward(self, x, lengths):
    h0 = torch.zeros(2 * self.num_layers, x.size(0), self.hidden_size).to(device)
    # Pack the padded sequence
    x_packed = nn.utils.rnn.pack_padded_sequence(x, lengths, batch_first=True, enforce_sorted=False)
    r_packed, h = self.rnn(x_packed, h0)
    # Unpack the sequence
    last_timestep = torch.cat((h[-2], h[-1]), dim=-1)
    y = self.fc(last_timestep)
    return y
  

def calculate_l2_distance(row):
    pred_x, pred_y = row['pred']
    actual_x, actual_y = row['actual']
    return np.sqrt((pred_x - actual_x)**2 + (pred_y - actual_y)**2)
  



plt.style.use('ggplot')
parser = create_parser()
args = parser.parse_args()

input_file = args.input
output_dir = args.output
input_name = input_file.split('_')[0]

cityA_df = pd.read_csv(input_file)
# cityB_df = pd.read_csv("data/cityB_challengedata.csv")
# cityC_df = pd.read_csv("data/cityC_challengedata.csv")
# cityD_df = pd.read_csv("data/cityD_challengedata.csv")


cityA_df = cityA_df[cityA_df['uid']<=1000]


cityA_train = cityA_df[cityA_df['d']<=30]

cityA_val = cityA_df[
        (cityA_df['d']<=50) &
        (cityA_df['d']>=31)
]

sequences = (
        cityA_train.sort_values(by=['t'])  # Sort by 't' in ascending order
        .groupby(['uid', 'd'])  # Group by 'uid' and 'd'
        .apply(lambda group: list(zip(group['x'], group['y'])))  # Create list of (x, y) tuples
        .reset_index(name='coordinates')  # Reset index and give the aggregated column a name
)

train_loader = process_df(cityA_train)
val_loader = process_df(cityA_val)


device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")


in_d = 2
out_d = in_d
hidden_d = 8
num_hidden = 1

rnn = coordRNN(in_d, out_d, hidden_d, num_hidden).to(device)

criterion = nn.MSELoss()
opt = optim.Adam(rnn.parameters(), lr=0.01)

loss = []
cumulative_error = 0
n_epochs = 50


for e in range(n_epochs):
  for x, y, lengths in train_loader:
    x, y, lengths = x.to(device), y.to(device), lengths.cpu()
    pred = rnn(x, lengths)  # predict next step, init hidden state to zero at the begining of the sequence

    err = criterion(pred, y)  # predict next step for each step
    opt.zero_grad()
    err.backward()
    opt.step()
    cumulative_error += err.item()

  cumulative_error /= len(train_loader)
  loss.append(cumulative_error)
  print(f"Epoch {e+1}, train loss: {cumulative_error}")


plt.plot(loss)
plt.ylabel('Loss')
plt.title(f"Training Loss for {input_name}")
plt.xlabel('Epoch')
plt.savefig(f"{output_dir}/{input_name}_trainingloss.png")
plt.close()


rnn.eval()
val_loss = 0.0
d = {
     "actual": [],
     "predicted": []
  }

with torch.no_grad():
  for x, y, lengths in val_loader:
    x, y, lengths = x.to(device), y.to(device), lengths.cpu()
    pred = rnn(x, lengths)

    d['actual'].append(y.cpu())
    d['predicted'].append(pred.cpu())

    loss = criterion(pred, y)
    val_loss += loss.item()

  avg_val_loss = val_loss / len(val_loader)
  print(f"Validation Loss: {avg_val_loss:.4f}\n")


actual = []
predicted = []
for i in range(len(d['actual'])):
    batched_actual = d['actual'][i]
    batched_pred = d['predicted'][i]
    actual.extend(list(np.array(batched_actual)))
    predicted.extend(list(np.array(batched_pred)))

df = pd.DataFrame(
    {
        "pred": predicted,
        "actual": actual
    }
)


# Apply function to each row to create the 'L2_distance' column
df['L2_distance'] = df.apply(calculate_l2_distance, axis=1)

plt.hist(df['L2_distance'], bins=50)
plt.title('L2 distance between Actual and Predicted Points')
plt.xlabel('L2 Distance')
plt.ylabel('Frequency')
plt.savefig(f"{output_dir}/{input_name}_L2dist.png")
plt.close()

actual, predicted = np.array(actual), np.array(predicted)

fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharex=True, sharey=True)

# Plot 1: Predicted
axes[0].scatter(predicted[:, 0], predicted[:, 1], label="Predicted", color="red", alpha=0.5)
axes[0].set_title("Predicted")
axes[0].legend()

# Plot 2: Actual
axes[1].scatter(actual[:, 0], actual[:, 1], label="Actual", color="blue", alpha=0.7)
axes[1].set_title("Actual")
axes[1].legend()

# Plot 3: Actual + Predicted
axes[2].scatter(actual[:, 0], actual[:, 1], label="Actual", color="blue", alpha=0.7)
axes[2].scatter(predicted[:, 0], predicted[:, 1], label="Predicted", color="red", alpha=0.5)
axes[2].set_title("Actual + Predicted")
axes[2].legend()

# Adjust layout to prevent overlap
plt.tight_layout()

# Save the combined plot to a file
output_file = f"{output_dir}/{input_name}_scatterplot.png"
plt.savefig(output_file, dpi=300, bbox_inches='tight')
print(f"Plot saved to {output_file}")
plt.close()
