import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim.lr_scheduler import CosineAnnealingWarmRestarts
import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import roc_curve, auc, classification_report, confusion_matrix
import seaborn as sns
from tqdm import tqdm

def train_classification_model_with_roc(model, train_loader, val_loader, 
                                      num_epochs=100, learning_rate=0.001, 
                                      device='cpu', save_best=True):
    """
    Train classification model with ROC plotting and weighted loss
    """
    model = model.to(device)
    
    # Get class distribution for weighted loss
    all_targets = []
    for _, targets in train_loader:
        all_targets.extend(targets.squeeze().numpy())
    
    class_counts = np.bincount(all_targets)
    print(f"Class counts: {class_counts}")
    
    # Create weighted loss function
    total_samples = sum(class_counts)
    class_weights = torch.FloatTensor([total_samples / (len(class_counts) * count) for count in class_counts])
    class_weights = class_weights.to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    
    # Optimizer and scheduler
    optimizer = optim.Adam(model.parameters(), lr=learning_rate, weight_decay=1e-5)
    scheduler = CosineAnnealingWarmRestarts(optimizer, T_0=20, T_mult=2, eta_min=1e-6)
    
    # Training history
    train_losses = []
    val_losses = []
    train_accuracies = []
    val_accuracies = []
    val_roc_aucs = []
    
    best_val_auc = 0.0
    best_model_state = None
    
    print(f"Training on {device}")
    print(f"Class weights: {class_weights}")
    
    for epoch in range(num_epochs):
        # Training phase
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0
        
        for sequences, targets in train_loader:
            sequences = sequences.to(device)
            targets = targets.squeeze().to(device)
            
            optimizer.zero_grad()
            outputs = model(sequences)
            loss = criterion(outputs, targets)
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item()
            _, predicted = torch.max(outputs.data, 1)
            train_total += targets.size(0)
            train_correct += (predicted == targets).sum().item()
        
        # Validation phase
        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_total = 0
        all_val_predictions = []
        all_val_probabilities = []
        all_val_targets = []
        
        with torch.no_grad():
            for sequences, targets in val_loader:
                sequences = sequences.to(device)
                targets = targets.squeeze().to(device)
                
                outputs = model(sequences)
                loss = criterion(outputs, targets)
                
                val_loss += loss.item()
                probabilities = torch.softmax(outputs, dim=1)
                _, predicted = torch.max(outputs.data, 1)
                
                val_total += targets.size(0)
                val_correct += (predicted == targets).sum().item()
                
                # Collect for ROC calculation
                all_val_predictions.extend(predicted.cpu().numpy())
                all_val_probabilities.extend(probabilities[:, 1].cpu().numpy())  # Positive class probability
                all_val_targets.extend(targets.cpu().numpy())
        
        # Calculate metrics
        train_loss = train_loss / len(train_loader)
        val_loss = val_loss / len(val_loader)
        train_accuracy = 100 * train_correct / train_total
        val_accuracy = 100 * val_correct / val_total
        
        # Calculate ROC AUC
        all_val_targets = np.array(all_val_targets)
        all_val_probabilities = np.array(all_val_probabilities)
        fpr, tpr, _ = roc_curve(all_val_targets, all_val_probabilities)
        val_roc_auc = auc(fpr, tpr)
        
        # Store history
        train_losses.append(train_loss)
        val_losses.append(val_loss)
        train_accuracies.append(train_accuracy)
        val_accuracies.append(val_accuracy)
        val_roc_aucs.append(val_roc_auc)
        
        # Save best model
        if val_roc_auc > best_val_auc:
            best_val_auc = val_roc_auc
            best_model_state = model.state_dict().copy()
        
        # Update scheduler
        scheduler.step()
        
        # Print progress
        if epoch % 10 == 0 or epoch == num_epochs - 1:
            print(f'Epoch {epoch:3d}: Train Loss: {train_loss:.4f}, Val Loss: {val_loss:.4f}, '
                  f'Train Acc: {train_accuracy:.2f}%, Val Acc: {val_accuracy:.2f}%, '
                  f'Val ROC AUC: {val_roc_auc:.4f}')
    
    # Load best model
    if save_best and best_model_state is not None:
        model.load_state_dict(best_model_state)
        print(f"Loaded best model with validation ROC AUC: {best_val_auc:.4f}")
    
    return model, {
        'train_losses': train_losses,
        'val_losses': val_losses,
        'train_accuracies': train_accuracies,
        'val_accuracies': val_accuracies,
        'val_roc_aucs': val_roc_aucs,
        'best_val_auc': best_val_auc
    }

def plot_training_history(history):
    """
    Plot training history with ROC AUC
    """
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle('Training History', fontsize=16, fontweight='bold')
    
    # Loss plot
    axes[0, 0].plot(history['train_losses'], label='Train Loss', color='blue')
    axes[0, 0].plot(history['val_losses'], label='Validation Loss', color='red')
    axes[0, 0].set_xlabel('Epoch')
    axes[0, 0].set_ylabel('Loss')
    axes[0, 0].set_title('Training and Validation Loss')
    axes[0, 0].legend()
    axes[0, 0].grid(True, alpha=0.3)
    
    # Accuracy plot
    axes[0, 1].plot(history['train_accuracies'], label='Train Accuracy', color='blue')
    axes[0, 1].plot(history['val_accuracies'], label='Validation Accuracy', color='red')
    axes[0, 1].set_xlabel('Epoch')
    axes[0, 1].set_ylabel('Accuracy (%)')
    axes[0, 1].set_title('Training and Validation Accuracy')
    axes[0, 1].legend()
    axes[0, 1].grid(True, alpha=0.3)
    
    # ROC AUC plot
    axes[1, 0].plot(history['val_roc_aucs'], label='Validation ROC AUC', color='green')
    axes[1, 0].set_xlabel('Epoch')
    axes[1, 0].set_ylabel('ROC AUC')
    axes[1, 0].set_title(f'Validation ROC AUC (Best: {history["best_val_auc"]:.4f})')
    axes[1, 0].legend()
    axes[1, 0].grid(True, alpha=0.3)
    
    # Combined metrics
    axes[1, 1].plot(history['val_accuracies'], label='Accuracy', color='red')
    axes[1, 1].plot(np.array(history['val_roc_aucs']) * 100, label='ROC AUC × 100', color='green')
    axes[1, 1].set_xlabel('Epoch')
    axes[1, 1].set_ylabel('Score')
    axes[1, 1].set_title('Validation Metrics Comparison')
    axes[1, 1].legend()
    axes[1, 1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.show()

def evaluate_model_comprehensive(model, val_loader, device='cpu'):
    """
    Comprehensive model evaluation with all metrics and plots
    """
    model.eval()
    model = model.to(device)
    
    all_predictions = []
    all_probabilities = []
    all_targets = []
    
    with torch.no_grad():
        for sequences, targets in val_loader:
            sequences = sequences.to(device)
            targets = targets.squeeze().to(device)
            
            outputs = model(sequences)
            probabilities = torch.softmax(outputs, dim=1)
            predictions = torch.argmax(outputs, dim=1)
            
            all_predictions.extend(predictions.cpu().numpy())
            all_probabilities.extend(probabilities[:, 1].cpu().numpy())
            all_targets.extend(targets.cpu().numpy())
    
    # Convert to numpy arrays
    all_predictions = np.array(all_predictions)
    all_probabilities = np.array(all_probabilities)
    all_targets = np.array(all_targets)
    
    # Print comprehensive report
    print("=" * 60)
    print("COMPREHENSIVE MODEL EVALUATION")
    print("=" * 60)
    
    print("\nClassification Report:")
    print(classification_report(all_targets, all_predictions, target_names=['≤$20', '>$20']))
    
    # Plot confusion matrix
    cm = confusion_matrix(all_targets, all_predictions)
    plt.figure(figsize=(8, 6))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', 
                xticklabels=['≤$20', '>$20'], 
                yticklabels=['≤$20', '>$20'])
    plt.title('Confusion Matrix')
    plt.ylabel('True Label')
    plt.xlabel('Predicted Label')
    plt.show()
    
    # Plot ROC curve
    fpr, tpr, thresholds = roc_curve(all_targets, all_probabilities)
    roc_auc = auc(fpr, tpr)
    
    plt.figure(figsize=(10, 8))
    plt.plot(fpr, tpr, color='darkorange', lw=2, label=f'ROC curve (AUC = {roc_auc:.3f})')
    plt.plot([0, 1], [0, 1], color='navy', lw=2, linestyle='--', label='Random classifier')
    plt.xlim([0.0, 1.0])
    plt.ylim([0.0, 1.05])
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title('ROC Curve')
    plt.legend(loc="lower right")
    plt.grid(True, alpha=0.3)
    plt.show()
    
    # Additional metrics
    print(f"\nDetailed Metrics:")
    print(f"ROC AUC: {roc_auc:.4f}")
    print(f"Number of samples: {len(all_targets)}")
    print(f"Class distribution: {np.bincount(all_targets)}")
    print(f"True Positives: {cm[1, 1]}")
    print(f"False Positives: {cm[0, 1]}")
    print(f"True Negatives: {cm[0, 0]}")
    print(f"False Negatives: {cm[1, 0]}")
    
    # Calculate additional metrics
    precision = cm[1, 1] / (cm[1, 1] + cm[0, 1]) if (cm[1, 1] + cm[0, 1]) > 0 else 0
    recall = cm[1, 1] / (cm[1, 1] + cm[1, 0]) if (cm[1, 1] + cm[1, 0]) > 0 else 0
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    print(f"Precision: {precision:.4f}")
    print(f"Recall: {recall:.4f}")
    print(f"F1-Score: {f1_score:.4f}")
    
    return {
        'predictions': all_predictions,
        'probabilities': all_probabilities,
        'targets': all_targets,
        'roc_auc': roc_auc,
        'confusion_matrix': cm,
        'precision': precision,
        'recall': recall,
        'f1_score': f1_score
    }

# Example usage
if __name__ == "__main__":
    print("Classification training utilities loaded successfully!")
    print("Use these functions with your classification model and data loaders.") 