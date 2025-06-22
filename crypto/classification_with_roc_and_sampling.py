import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_curve, auc, classification_report, confusion_matrix
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

class BTCDatasetClassification(Dataset):
    def __init__(self, sequences, targets, sequence_scaler=None, fit_scalers=True):
        """
        BTC Dataset for classification with built-in scaling
        """
        self.sequences = sequences
        self.targets = targets
        
        # Scale sequences
        if fit_scalers:
            self.sequence_scaler = StandardScaler()
            # Reshape for sklearn: (n_samples, n_features)
            sequences_reshaped = sequences.reshape(-1, sequences.shape[-1])
            self.scaled_sequences = self.sequence_scaler.fit_transform(sequences_reshaped)
            # Reshape back: (n_samples, sequence_length, n_features)
            self.scaled_sequences = self.scaled_sequences.reshape(sequences.shape)
        else:
            self.sequence_scaler = sequence_scaler
            sequences_reshaped = sequences.reshape(-1, sequences.shape[-1])
            self.scaled_sequences = self.sequence_scaler.transform(sequences_reshaped)
            self.scaled_sequences = self.scaled_sequences.reshape(sequences.shape)
        
        print(f"Dataset created with {len(self.sequences)} samples")
        print(f"Sequence shape: {self.scaled_sequences.shape}")
        print(f"Target shape: {self.targets.shape}")
        
    def __len__(self):
        return len(self.sequences)
    
    def __getitem__(self, idx):
        sequence = torch.FloatTensor(self.scaled_sequences[idx])
        target = torch.LongTensor([self.targets[idx]])  # For classification
        return sequence, target
    
    def get_train_loader(self, batch_size=32, shuffle=True, weighted_sampling=True):
        if weighted_sampling:
            # Calculate class weights for weighted sampling
            class_counts = np.bincount(self.targets)
            class_weights = 1.0 / class_counts
            sample_weights = class_weights[self.targets]
            
            # Create weighted sampler
            sampler = WeightedRandomSampler(
                weights=sample_weights,
                num_samples=len(self.targets),
                replacement=True
            )
            
            return DataLoader(self, batch_size=batch_size, sampler=sampler)
        else:
            return DataLoader(self, batch_size=batch_size, shuffle=shuffle)
    
    def get_val_loader(self, batch_size=32, shuffle=False):
        return DataLoader(self, batch_size=batch_size, shuffle=shuffle)

def setup_classification_data_with_weighted_sampling(X_DATASET, Y_BINARY, train_batch_size=32, val_batch_size=32):
    """
    Setup with weighted sampling for imbalanced classes
    """
    # Check class distribution
    unique_classes, class_counts = np.unique(Y_BINARY, return_counts=True)
    print(f"Original class distribution: {dict(zip(unique_classes, class_counts))}")
    
    # Split data (without stratification to avoid the error)
    X_train, X_val, y_train, y_val = train_test_split(
        X_DATASET, Y_BINARY, test_size=0.2, random_state=42, stratify=None
    )
    
    print(f"Training set: {len(X_train)} samples")
    print(f"Validation set: {len(X_val)} samples")
    
    # Check class distribution in splits
    train_classes, train_counts = np.unique(y_train, return_counts=True)
    val_classes, val_counts = np.unique(y_val, return_counts=True)
    
    print(f"Training class distribution: {dict(zip(train_classes, train_counts))}")
    print(f"Validation class distribution: {dict(zip(val_classes, val_counts))}")
    
    # Create datasets
    print("=== Creating Training Dataset ===")
    train_dataset = BTCDatasetClassification(X_train, y_train, fit_scalers=True)
    
    print("=== Creating Validation Dataset ===")
    val_dataset = BTCDatasetClassification(X_val, y_val, fit_scalers=False, 
                                         sequence_scaler=train_dataset.sequence_scaler)
    
    # Create data loaders with weighted sampling
    train_loader = train_dataset.get_train_loader(batch_size=train_batch_size, weighted_sampling=True)
    val_loader = val_dataset.get_val_loader(batch_size=val_batch_size, shuffle=False)
    
    return train_loader, val_loader, train_dataset.sequence_scaler

def plot_roc_curve(y_true, y_pred_proba, title="ROC Curve"):
    """
    Plot ROC curve with AUC score
    """
    fpr, tpr, thresholds = roc_curve(y_true, y_pred_proba)
    roc_auc = auc(fpr, tpr)
    
    plt.figure(figsize=(10, 8))
    plt.plot(fpr, tpr, color='darkorange', lw=2, label=f'ROC curve (AUC = {roc_auc:.3f})')
    plt.plot([0, 1], [0, 1], color='navy', lw=2, linestyle='--', label='Random classifier')
    plt.xlim([0.0, 1.0])
    plt.ylim([0.0, 1.05])
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title(title)
    plt.legend(loc="lower right")
    plt.grid(True, alpha=0.3)
    plt.show()
    
    return roc_auc, fpr, tpr, thresholds

def plot_confusion_matrix(y_true, y_pred, title="Confusion Matrix"):
    """
    Plot confusion matrix with heatmap
    """
    cm = confusion_matrix(y_true, y_pred)
    
    plt.figure(figsize=(8, 6))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', 
                xticklabels=['≤$20', '>$20'], 
                yticklabels=['≤$20', '>$20'])
    plt.title(title)
    plt.ylabel('True Label')
    plt.xlabel('Predicted Label')
    plt.show()
    
    return cm

def evaluate_classification_model(model, val_loader, device='cpu'):
    """
    Comprehensive evaluation of classification model
    """
    model.eval()
    model = model.to(device)
    
    all_predictions = []
    all_probabilities = []
    all_targets = []
    
    with torch.no_grad():
        for sequences, targets in val_loader:
            sequences = sequences.to(device)
            targets = targets.to(device)
            
            # Get model outputs
            outputs = model(sequences)
            probabilities = torch.softmax(outputs, dim=1)
            predictions = torch.argmax(outputs, dim=1)
            
            # Collect results
            all_predictions.extend(predictions.cpu().numpy())
            all_probabilities.extend(probabilities[:, 1].cpu().numpy())  # Probability of positive class
            all_targets.extend(targets.squeeze().cpu().numpy())
    
    # Convert to numpy arrays
    all_predictions = np.array(all_predictions)
    all_probabilities = np.array(all_probabilities)
    all_targets = np.array(all_targets)
    
    # Print classification report
    print("Classification Report:")
    print(classification_report(all_targets, all_predictions, target_names=['≤$20', '>$20']))
    
    # Plot confusion matrix
    plot_confusion_matrix(all_targets, all_predictions)
    
    # Plot ROC curve
    roc_auc, fpr, tpr, thresholds = plot_roc_curve(all_targets, all_probabilities)
    
    # Additional metrics
    print(f"\nROC AUC: {roc_auc:.3f}")
    print(f"Number of samples: {len(all_targets)}")
    print(f"Class distribution: {np.bincount(all_targets)}")
    
    return all_predictions, all_probabilities, all_targets, roc_auc

def create_weighted_loss_function(class_counts):
    """
    Create weighted loss function for imbalanced classes
    """
    # Calculate class weights (inverse of class frequencies)
    total_samples = sum(class_counts)
    class_weights = torch.FloatTensor([total_samples / (len(class_counts) * count) for count in class_counts])
    
    print(f"Class weights: {class_weights}")
    
    return nn.CrossEntropyLoss(weight=class_weights)

# Example usage and testing
if __name__ == "__main__":
    # Create some test data with imbalance
    np.random.seed(42)
    X_test = np.random.randn(1000, 5, 10)  # 1000 samples, 5 timesteps, 10 features
    y_test = np.random.randint(0, 2, 1000)  # Binary classification
    
    # Make it imbalanced (90% class 0, 10% class 1)
    y_test[:900] = 0  # 900 samples of class 0
    y_test[900:] = 1  # 100 samples of class 1
    
    print("Testing classification setup with weighted sampling...")
    train_loader, val_loader, scaler = setup_classification_data_with_weighted_sampling(X_test, y_test)
    
    # Test the data loaders
    print("\nTesting data loaders...")
    for batch_idx, (sequences, targets) in enumerate(train_loader):
        print(f"Batch {batch_idx}: sequences shape {sequences.shape}, targets shape {targets.shape}")
        if batch_idx >= 2:  # Just show first few batches
            break
    
    print("\nSetup completed successfully!") 