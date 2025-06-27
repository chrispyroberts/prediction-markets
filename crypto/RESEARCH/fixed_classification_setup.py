import torch
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import numpy as np

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
    
    def get_train_loader(self, batch_size=32, shuffle=True):
        return DataLoader(self, batch_size=batch_size, shuffle=shuffle)
    
    def get_val_loader(self, batch_size=32, shuffle=False):
        return DataLoader(self, batch_size=batch_size, shuffle=shuffle)

def setup_classification_data_fixed(X_DATASET, Y_BINARY, train_batch_size=32, val_batch_size=32):
    """
    Fixed setup for classification data that handles imbalanced classes
    """
    # Check class distribution
    unique_classes, class_counts = np.unique(Y_BINARY, return_counts=True)
    print(f"Class distribution: {dict(zip(unique_classes, class_counts))}")
    
    # Determine if we can use stratified splitting
    min_class_count = min(class_counts)
    can_stratify = min_class_count >= 2
    
    if can_stratify:
        print("Using stratified train-test split")
        X_train, X_val, y_train, y_val = train_test_split(
            X_DATASET, Y_BINARY, test_size=0.2, random_state=42, stratify=Y_BINARY
        )
    else:
        print(f"Cannot use stratified split (minimum class count: {min_class_count})")
        print("Using regular train-test split")
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
    
    # Create data loaders
    train_loader = train_dataset.get_train_loader(batch_size=train_batch_size, shuffle=True)
    val_loader = val_dataset.get_val_loader(batch_size=val_batch_size, shuffle=False)
    
    return train_loader, val_loader, train_dataset.sequence_scaler

def setup_classification_data_with_sampling(X_DATASET, Y_BINARY, train_batch_size=32, val_batch_size=32):
    """
    Setup with class balancing using sampling
    """
    # Check class distribution
    unique_classes, class_counts = np.unique(Y_BINARY, return_counts=True)
    print(f"Original class distribution: {dict(zip(unique_classes, class_counts))}")
    
    # Split first
    X_train, X_val, y_train, y_val = train_test_split(
        X_DATASET, Y_BINARY, test_size=0.2, random_state=42, stratify=None
    )
    
    # Reshape for sampling (flatten sequences)
    X_train_flat = X_train.reshape(X_train.shape[0], -1)
    
    # Apply SMOTE for oversampling minority class
    try:
        from imblearn.over_sampling import SMOTE
        smote = SMOTE(random_state=42)
        X_train_balanced, y_train_balanced = smote.fit_resample(X_train_flat, y_train)
        
        # Reshape back to original shape
        X_train_balanced = X_train_balanced.reshape(-1, X_train.shape[1], X_train.shape[2])
        
        print(f"Balanced training set: {len(X_train_balanced)} samples")
        balanced_classes, balanced_counts = np.unique(y_train_balanced, return_counts=True)
        print(f"Balanced class distribution: {dict(zip(balanced_classes, balanced_counts))}")
        
        # Create datasets
        train_dataset = BTCDatasetClassification(X_train_balanced, y_train_balanced, fit_scalers=True)
        val_dataset = BTCDatasetClassification(X_val, y_val, fit_scalers=False, 
                                             sequence_scaler=train_dataset.sequence_scaler)
        
    except ImportError:
        print("imblearn not available, using original data")
        train_dataset = BTCDatasetClassification(X_train, y_train, fit_scalers=True)
        val_dataset = BTCDatasetClassification(X_val, y_val, fit_scalers=False, 
                                             sequence_scaler=train_dataset.sequence_scaler)
    
    # Create data loaders
    train_loader = train_dataset.get_train_loader(batch_size=train_batch_size, shuffle=True)
    val_loader = val_dataset.get_val_loader(batch_size=val_batch_size, shuffle=False)
    
    return train_loader, val_loader, train_dataset.sequence_scaler

# Test the functions
if __name__ == "__main__":
    # Create some test data
    np.random.seed(42)
    X_test = np.random.randn(100, 5, 10)  # 100 samples, 5 timesteps, 10 features
    y_test = np.random.randint(0, 2, 100)  # Binary classification
    
    # Make it slightly imbalanced
    y_test[:95] = 0  # 95 samples of class 0
    y_test[95:] = 1  # 5 samples of class 1
    
    print("Testing fixed classification setup...")
    train_loader, val_loader, scaler = setup_classification_data_fixed(X_test, y_test)
    
    print("\nTesting sampling setup...")
    train_loader2, val_loader2, scaler2 = setup_classification_data_with_sampling(X_test, y_test) 