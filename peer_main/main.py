import os
import argparse
import torch
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data.distributed import DistributedSampler
from torch.utils.data import DataLoader
from transformers import GPT2Tokenizer
from peer.dataset import PileDataset
from peer.model import PEERLanguageModel
from peer.trainer import train, validate
import matplotlib.pyplot as plt

def plot_losses(train_losses, val_losses, epoch, save_dir):
    plt.figure(figsize=(10, 5))
    plt.plot(train_losses, label='Train Loss')
    plt.plot(val_losses, label='Validation Loss')
    plt.xlabel('Batch')
    plt.ylabel('Loss')
    plt.title(f'Epoch {epoch+1} Losses')
    plt.legend()
    plt.savefig(os.path.join(save_dir, f'epoch_{epoch+1}_losses.png'))
    plt.close()

# main execution
def main(args):
    dist.init_process_group(backend='nccl')
    local_rank = int(os.environ["LOCAL_RANK"])
    torch.cuda.set_device(local_rank)
    device = torch.device("cuda", local_rank)

    # Hyperparameters
    vocab_size = int(args.vocab_size)  # GPT-2 tokenizer vocab size
    dim = int(args.dim)
    num_layers = int(args.num_layers)
    num_heads = int(args.num_heads)
    num_experts = int(args.num_experts)
    top_k = int(args.top_k)
    batch_size = int(args.batch_size)
    num_epochs = int(args.num_epochs)
    learning_rate = float(args.learning_rate)
    dataset = args.dataset

    print(vars(args))
    
    # Initialize tokenizer and model
    print("Loading pretrained GPT2 tokenizer transformer")
    tokenizer = GPT2Tokenizer.from_pretrained('gpt2')
    tokenizer.pad_token = tokenizer.eos_token
    print("Finished loading pretrained GPT2 tokenizer transformer")
    
    print("Initalizing PEER model")
    model = PEERLanguageModel(vocab_size, dim, num_layers, num_heads, num_experts, top_k).to(device)
    print("Finished initalizing PEER model")

    # Wrap the model with DistributedDataParallel
    #print("Initalizing PEER model with DistributedDataParallel")
    #model = DDP(model, device_ids=[local_rank], output_device=local_rank)
    #print("Finished initalizing PEER model with DistributedDataParallel")

    # Load Pile dataset
    print("Loading datasets")
    train_dataset = PileDataset(dataset, tokenizer, split='train')
    val_dataset = PileDataset(dataset, tokenizer, split='validation')
    print("Finished loading datasets")

    # Use DistributedSampler for the training data
    train_sampler = DistributedSampler(train_dataset)
    train_loader = DataLoader(train_dataset, batch_size=batch_size, sampler=train_sampler)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
    
    # Optimizer
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    
    if local_rank == 0:
        print("Number of parameters:", sum(p.numel() for p in model.parameters()))
        os.makedirs('plots', exist_ok=True)
    
    # Training and validation loop
    best_val_loss = float('inf')
    for epoch in range(num_epochs):
        train_sampler.set_epoch(epoch)
        if local_rank == 0:
            print(f"Epoch Training {epoch+1}/{num_epochs}")
        train_loss, train_batch_losses = train(model, train_loader, optimizer, device)
        if local_rank == 0:
            print(f"Epoch Validation {epoch+1}/{num_epochs}")
            val_loss, val_perplexity, val_batch_losses = validate(model, val_loader, device)
            print(f"Epoch {epoch+1}/{num_epochs}, Train Loss: {train_loss:.4f}, Val Loss: {val_loss:.4f}, Val Perplexity: {val_perplexity:.4f}")
            
            # Plot and save losses
            plot_losses(train_batch_losses, val_batch_losses, epoch, 'plots')
        
            # Save the best model
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                torch.save(model.state_dict(), 'best_peer_language_model.pth')
    
    # Save the final trained model
    if local_rank == 0:
        torch.save(model.state_dict(), 'final_peer_language_model.pth')

    # Clean up
    dist.destroy_process_group()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--vocab-size")
    parser.add_argument("--dim")
    parser.add_argument("--num-layers")
    parser.add_argument("--num-heads")
    parser.add_argument("--num-experts")
    parser.add_argument("--top-k")
    parser.add_argument("--batch-size")
    parser.add_argument("--num-epochs")
    parser.add_argument("--learning-rate")
    parser.add_argument("--dataset")
    args = parser.parse_args()

    main(args)