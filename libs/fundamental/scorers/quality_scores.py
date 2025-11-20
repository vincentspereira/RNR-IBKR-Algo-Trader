"""Quality scoring models (Piotroski, Altman, Beneish)."""
from typing import Dict
from decimal import Decimal


class PiotroskiScore:
    """Calculate Piotroski F-Score (0-9)."""
    
    @staticmethod
    def calculate(financial_data: Dict) -> int:
        """
        Calculate Piotroski F-Score.
        
        Args:
            financial_data: Financial statement data
            
        Returns:
            F-Score (0-9)
        """
        score = 0
        
        # Profitability (4 points)
        if financial_data.get('net_income', 0) > 0:
            score += 1
        if financial_data.get('operating_cash_flow', 0) > 0:
            score += 1
        if financial_data.get('roa_change', 0) > 0:
            score += 1
        if financial_data.get('operating_cash_flow', 0) > financial_data.get('net_income', 0):
            score += 1
        
        # Leverage/Liquidity (3 points)
        if financial_data.get('long_term_debt_change', 0) < 0:
            score += 1
        if financial_data.get('current_ratio_change', 0) > 0:
            score += 1
        if financial_data.get('shares_outstanding_change', 0) <= 0:
            score += 1
        
        # Operating Efficiency (2 points)
        if financial_data.get('gross_margin_change', 0) > 0:
            score += 1
        if financial_data.get('asset_turnover_change', 0) > 0:
            score += 1
        
        return score


class AltmanZScore:
    """Calculate Altman Z-Score for bankruptcy prediction."""
    
    @staticmethod
    def calculate(financial_data: Dict) -> float:
        """
        Calculate Altman Z-Score.
        
        Args:
            financial_data: Financial statement data
            
        Returns:
            Z-Score (higher is better, >2.99 is safe zone)
        """
        # Extract data
        working_capital = financial_data.get('working_capital', 0)
        total_assets = financial_data.get('total_assets', 1)
        retained_earnings = financial_data.get('retained_earnings', 0)
        ebit = financial_data.get('ebit', 0)
        market_value_equity = financial_data.get('market_value_equity', 0)
        total_liabilities = financial_data.get('total_liabilities', 1)
        sales = financial_data.get('sales', 0)
        
        # Z-Score formula
        x1 = working_capital / total_assets
        x2 = retained_earnings / total_assets
        x3 = ebit / total_assets
        x4 = market_value_equity / total_liabilities
        x5 = sales / total_assets
        
        z_score = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
        
        return float(z_score)
    
    @staticmethod
    def interpret(z_score: float) -> str:
        """
        Interpret Z-Score.
        
        Args:
            z_score: Calculated Z-Score
            
        Returns:
            Zone classification
        """
        if z_score > 2.99:
            return "SAFE"
        elif z_score >= 1.81:
            return "GREY"
        else:
            return "DISTRESS"


class BeneishMScore:
    """Calculate Beneish M-Score for earnings manipulation detection."""
    
    @staticmethod
    def calculate(financial_data: Dict) -> float:
        """
        Calculate Beneish M-Score.
        
        Args:
            financial_data: Financial statement data
            
        Returns:
            M-Score (> -2.22 suggests manipulation)
        """
        # This is a simplified version - full calculation requires 2 years of data
        # For demonstration purposes
        
        dsri = financial_data.get('dsri', 1.0)  # Days Sales in Receivables Index
        gmi = financial_data.get('gmi', 1.0)    # Gross Margin Index
        aqi = financial_data.get('aqi', 1.0)    # Asset Quality Index
        sgi = financial_data.get('sgi', 1.0)    # Sales Growth Index
        depi = financial_data.get('depi', 1.0)  # Depreciation Index
        sgai = financial_data.get('sgai', 1.0)  # SG&A Index
        lvgi = financial_data.get('lvgi', 1.0)  # Leverage Index
        tata = financial_data.get('tata', 0.0)  # Total Accruals to Total Assets
        
        m_score = (
            -4.84 +
            0.920 * dsri +
            0.528 * gmi +
            0.404 * aqi +
            0.892 * sgi +
            0.115 * depi -
            0.172 * sgai +
            4.679 * tata -
            0.327 * lvgi
        )
        
        return float(m_score)


class QualityScorer:
    """Main quality scorer combining all scoring models."""
    
    def __init__(self):
        self.piotroski = PiotroskiScore()
        self.altman = AltmanZScore()
        self.beneish = BeneishMScore()
    
    def calculate_all_scores(self, financial_data: Dict) -> Dict:
        """
        Calculate all quality scores.
        
        Args:
            financial_data: Financial statement data
            
        Returns:
            Dictionary of quality scores
        """
        piotroski_score = self.piotroski.calculate(financial_data)
        altman_score = self.altman.calculate(financial_data)
        beneish_score = self.beneish.calculate(financial_data)
        
        # Composite score (0-100)
        composite = (
            (piotroski_score / 9.0) * 40 +  # 40% weight
            (1 if altman_score > 2.99 else 0.5 if altman_score >= 1.81 else 0) * 30 +  # 30% weight
            (1 if beneish_score < -2.22 else 0) * 30  # 30% weight
        )
        
        return {
            'piotroski_f_score': piotroski_score,
            'altman_z_score': altman_score,
            'altman_zone': self.altman.interpret(altman_score),
            'beneish_m_score': beneish_score,
            'composite_score': composite
        }
