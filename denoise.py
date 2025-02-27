import torch
import torch.nn.functional as F
from torch.optim import Adam

from einops import rearrange, repeat

import sidechainnet as scn
from equiformer_pytorch import Equiformer

BATCH_SIZE = 1
GRADIENT_ACCUMULATE_EVERY = 16
MAX_SEQ_LEN = 512
DEFAULT_TYPE = torch.float64

torch.set_default_dtype(DEFAULT_TYPE)

def cycle(loader, len_thres = MAX_SEQ_LEN):
    while True:
        for data in loader:
            if data.seqs.shape[1] > len_thres:
                continue
            yield data

transformer = Equiformer(
    num_tokens = 24,
    dim = (16, 8, 8, 8),
    dim_head = (16, 8, 8, 8),
    heads = (4, 2, 2, 2),
    depth = 10,
    reversible = True,
    attend_self = True,
    reduce_dim_out = True,
    num_neighbors = 6,
    num_degrees = 4,
    linear_out = True
).cuda()

data = scn.load(
    casp_version = 12,
    thinning = 30,
    with_pytorch = 'dataloaders',
    batch_size = BATCH_SIZE,
    dynamic_batching = False    
)

# Add gaussian noise to the coords
# Testing the refinement algorithm

dl = cycle(data['train'])
optim = Adam(transformer.parameters(), lr = 1e-4)

for _ in range(10000):
    for _ in range(GRADIENT_ACCUMULATE_EVERY):
        batch = next(dl)
        seqs, coords, masks = batch.seqs, batch.crds, batch.msks

        seqs = seqs.cuda().argmax(dim = -1)
        coords = coords.cuda().type(torch.get_default_dtype())
        masks = masks.cuda().bool()

        l = seqs.shape[1]
        coords = rearrange(coords, 'b (l s) c -> b l s c', s = 14)

        # Keeping only the backbone coordinates
        coords = coords[:, :, 0:3, :]
        coords = rearrange(coords, 'b l s c -> b (l s) c')

        seq = repeat(seqs, 'b n -> b (n c)', c = 3)
        masks = repeat(masks, 'b n -> b (n c)', c = 3)

        noised_coords = coords + torch.randn_like(coords).cuda()

        _, type1_out = transformer(
            seq,
            noised_coords,
            mask = masks
        )

        denoised_coords = noised_coords + type1_out

        loss = F.mse_loss(denoised_coords[masks], coords[masks]) 
        (loss / GRADIENT_ACCUMULATE_EVERY).backward()

    print('loss:', loss.item())
    optim.step()
    optim.zero_grad()
