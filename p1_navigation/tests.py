import torch
#device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
#print(device)

print(torch.cuda.is_available())

print(torch.cuda.current_device())
