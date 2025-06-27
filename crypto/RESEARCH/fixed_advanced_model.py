import torch
import torch.nn as nn
import torch.nn.functional as F
import math

class TemporalBlock(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, dilation):
        super(TemporalBlock, self).__init__()
        
        self.conv1 = nn.Conv1d(in_channels, out_channels, kernel_size, 
                              dilation=dilation, padding=(kernel_size-1)*dilation)
        self.bn1 = nn.BatchNorm1d(out_channels)
        self.conv2 = nn.Conv1d(out_channels, out_channels, kernel_size, 
                              dilation=dilation, padding=(kernel_size-1)*dilation)
        self.bn2 = nn.BatchNorm1d(out_channels)
        
        # Proper skip connection
        self.downsample = nn.Conv1d(in_channels, out_channels, 1) if in_channels != out_channels else None
        
    def forward(self, x):
        identity = x
        
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        
        if self.downsample:
            identity = self.downsample(identity)
        
        # Ensure dimensions match before adding
        if out.size() != identity.size():
            # Pad or crop identity to match output size
            if out.size(-1) > identity.size(-1):
                # Pad identity
                pad_size = out.size(-1) - identity.size(-1)
                identity = F.pad(identity, (0, pad_size))
            else:
                # Crop identity
                identity = identity[:, :, :out.size(-1)]
        
        out += identity
        return F.relu(out)

class AdvancedFinancialPredictor(nn.Module):
    def __init__(self, input_features=20, sequence_length=5, hidden_dim=128):
        super(AdvancedFinancialPredictor, self).__init__()
        
        self.input_features = input_features
        self.sequence_length = sequence_length
        self.hidden_dim = hidden_dim
        
        # 1. Multi-scale Feature Extraction
        self.multi_scale_conv = nn.ModuleList([
            nn.Conv1d(input_features, hidden_dim//4, kernel_size=1, padding=0),
            nn.Conv1d(input_features, hidden_dim//4, kernel_size=3, padding=1),
            nn.Conv1d(input_features, hidden_dim//4, kernel_size=5, padding=2),
            nn.Conv1d(input_features, hidden_dim//4, kernel_size=7, padding=3),
        ])
        
        # 2. TCN blocks with proper dimensions
        self.tcn_blocks = nn.ModuleList([
            TemporalBlock(hidden_dim, hidden_dim, kernel_size=3, dilation=1),
            TemporalBlock(hidden_dim, hidden_dim, kernel_size=3, dilation=2),
            TemporalBlock(hidden_dim, hidden_dim, kernel_size=3, dilation=4),
        ])
        
        # 3. LSTM layer
        self.lstm = nn.LSTM(hidden_dim, hidden_dim//2, num_layers=2, 
                           bidirectional=True, batch_first=True, dropout=0.2)
        
        # 4. Attention mechanism
        self.attention = nn.MultiheadAttention(hidden_dim, num_heads=8, 
                                             dropout=0.1, batch_first=True)
        
        # 5. Global pooling
        self.adaptive_pool = nn.AdaptiveAvgPool1d(1)
        self.max_pool = nn.AdaptiveMaxPool1d(1)
        
        # 6. Dense layers
        self.fc1 = nn.Linear(hidden_dim * 2, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim // 2)
        self.fc3 = nn.Linear(hidden_dim // 2, 1)
        
        # 7. Dropout and normalization
        self.dropout = nn.Dropout(0.3)
        self.layer_norm = nn.LayerNorm(hidden_dim)
        
        # Initialize weights
        self._initialize_weights()
    
    def _initialize_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Conv1d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.Linear):
                nn.init.xavier_normal_(m.weight)
                nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.LSTM):
                for name, param in m.named_parameters():
                    if 'weight' in name:
                        nn.init.orthogonal_(param)
                    elif 'bias' in name:
                        nn.init.constant_(param, 0)
    
    def forward(self, x):
        # Input: (batch_size, sequence_length, input_features)
        batch_size = x.size(0)
        
        # Transpose for conv1d: (batch_size, input_features, sequence_length)
        x = x.transpose(1, 2)
        
        # 1. Multi-scale feature extraction
        multi_scale_features = []
        for conv in self.multi_scale_conv:
            multi_scale_features.append(conv(x))
        x = torch.cat(multi_scale_features, dim=1)  # (batch_size, hidden_dim, sequence_length)
        
        # 2. TCN blocks
        for tcn_block in self.tcn_blocks:
            x = tcn_block(x)
        
        # 3. Transpose for LSTM: (batch_size, sequence_length, hidden_dim)
        x = x.transpose(1, 2)
        
        # 4. LSTM processing
        lstm_out, _ = self.lstm(x)
        
        # 5. Self-attention
        attn_out, _ = self.attention(lstm_out, lstm_out, lstm_out)
        
        # 6. Layer normalization
        x = self.layer_norm(attn_out)
        
        # 7. Global pooling
        x_transposed = x.transpose(1, 2)  # (batch_size, hidden_dim, sequence_length)
        avg_pooled = self.adaptive_pool(x_transposed).squeeze(-1)
        max_pooled = self.max_pool(x_transposed).squeeze(-1)
        pooled = torch.cat([avg_pooled, max_pooled], dim=1)  # (batch_size, hidden_dim * 2)
        
        # 8. Dense layers
        x = F.relu(self.fc1(pooled))
        x = self.dropout(x)
        
        x = F.relu(self.fc2(x))
        x = self.dropout(x)
        
        output = self.fc3(x)
        
        return output

# Simplified but effective model
class SimpleAdvancedModel(nn.Module):
    def __init__(self, input_features=20, sequence_length=5):
        super(SimpleAdvancedModel, self).__init__()
        
        self.input_features = input_features
        self.sequence_length = sequence_length
        
        # Feature extraction
        self.feature_extractor = nn.Sequential(
            nn.Conv1d(input_features, 64, kernel_size=3, padding=1),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Dropout(0.2),
            
            nn.Conv1d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(0.2),
            
            nn.Conv1d(128, 64, kernel_size=3, padding=1),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Dropout(0.2),
        )
        
        # LSTM layer
        self.lstm = nn.LSTM(64, 32, num_layers=2, bidirectional=True, 
                           batch_first=True, dropout=0.2)
        
        # Attention
        self.attention = nn.MultiheadAttention(64, num_heads=4, 
                                             dropout=0.1, batch_first=True)
        
        # Global pooling
        self.global_pool = nn.AdaptiveAvgPool1d(1)
        
        # Dense layers
        self.fc1 = nn.Linear(64, 32)
        self.fc2 = nn.Linear(32, 1)
        
        self.dropout = nn.Dropout(0.3)
        
    def forward(self, x):
        # Input: (batch_size, sequence_length, input_features)
        batch_size = x.size(0)
        
        # Transpose for conv1d
        x = x.transpose(1, 2)  # (batch_size, input_features, sequence_length)
        
        # Feature extraction
        x = self.feature_extractor(x)  # (batch_size, 64, sequence_length)
        
        # Transpose for LSTM
        x = x.transpose(1, 2)  # (batch_size, sequence_length, 64)
        
        # LSTM
        lstm_out, _ = self.lstm(x)
        
        # Attention
        attn_out, _ = self.attention(lstm_out, lstm_out, lstm_out)
        
        # Global pooling
        x = attn_out.transpose(1, 2)  # (batch_size, 64, sequence_length)
        x = self.global_pool(x)  # (batch_size, 64, 1)
        x = x.squeeze(-1)  # (batch_size, 64)
        
        # Dense layers
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = self.fc2(x)
        
        return x

# Test the model
def test_model():
    # Test data
    batch_size = 4
    sequence_length = 5
    input_features = 20
    
    x = torch.randn(batch_size, sequence_length, input_features)
    
    # Test SimpleAdvancedModel
    model = SimpleAdvancedModel(input_features, sequence_length)
    output = model(x)
    print(f"SimpleAdvancedModel output shape: {output.shape}")
    
    # Test AdvancedFinancialPredictor
    model2 = AdvancedFinancialPredictor(input_features, sequence_length)
    output2 = model2(x)
    print(f"AdvancedFinancialPredictor output shape: {output2.shape}")
    
    return model, model2

if __name__ == "__main__":
    test_model() 