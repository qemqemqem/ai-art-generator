"""Tests for interactive mode queue and API endpoints."""

import pytest
from datetime import datetime

from app.queue_manager import (
    QueueManager,
    ApprovalItem,
    ApprovalType,
    GeneratedOption,
    ApprovalDecision,
    QueueStatus,
)
from app.models import Asset, AssetStatus


class TestQueueManager:
    """Tests for the QueueManager class."""

    def test_initial_status(self):
        """Test initial queue status is empty."""
        qm = QueueManager()
        status = qm.get_status()
        
        assert status.total_assets == 0
        assert status.completed_assets == 0
        assert status.awaiting_approval == 0
        assert status.currently_generating == 0
        assert status.is_running == False
        assert status.is_paused == False

    def test_add_assets(self):
        """Test adding assets to the queue."""
        qm = QueueManager()
        
        assets = [
            Asset(id="asset_1", input_description="A fire dragon"),
            Asset(id="asset_2", input_description="An ice wizard"),
            Asset(id="asset_3", input_description="A forest spirit"),
        ]
        
        qm.add_assets(assets)
        status = qm.get_status()
        
        assert status.total_assets == 3
        assert status.pending == 3

    def test_add_approval_item(self):
        """Test adding an item to the approval queue."""
        qm = QueueManager()
        
        item = ApprovalItem(
            asset_id="asset_1",
            asset_description="A fire dragon",
            step_id="portrait",
            step_name="generate_image",
            step_index=0,
            total_steps=3,
            approval_type=ApprovalType.CHOOSE_ONE,
            options=[
                GeneratedOption(id="opt_1", type="image", image_data_url="data:image/png;base64,abc"),
                GeneratedOption(id="opt_2", type="image", image_data_url="data:image/png;base64,def"),
            ],
            context={"description": "A fire dragon"},
        )
        
        qm.add_approval_item(item)
        status = qm.get_status()
        
        assert status.awaiting_approval == 1

    def test_get_next_approval(self):
        """Test getting the next approval item."""
        qm = QueueManager()
        
        # Initially none
        assert qm.get_next_approval() is None
        
        # Add an item
        item = ApprovalItem(
            asset_id="asset_1",
            asset_description="A fire dragon",
            step_id="portrait",
            step_name="generate_image",
            step_index=0,
            total_steps=3,
            approval_type=ApprovalType.CHOOSE_ONE,
            options=[],
            context={},
        )
        qm.add_approval_item(item)
        
        # Now we should get it
        next_item = qm.get_next_approval()
        assert next_item is not None
        assert next_item.asset_id == "asset_1"

    def test_get_all_approvals(self):
        """Test getting all approval items."""
        qm = QueueManager()
        
        # Add multiple items
        for i in range(3):
            item = ApprovalItem(
                asset_id=f"asset_{i}",
                asset_description=f"Description {i}",
                step_id="portrait",
                step_name="generate_image",
                step_index=0,
                total_steps=3,
                approval_type=ApprovalType.CHOOSE_ONE,
                options=[],
                context={},
            )
            qm.add_approval_item(item)
        
        items = qm.get_all_approvals()
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_submit_approval_choose_one(self):
        """Test approving an item in choose_one mode."""
        qm = QueueManager()
        
        item = ApprovalItem(
            id="item_1",
            asset_id="asset_1",
            asset_description="A fire dragon",
            step_id="portrait",
            step_name="generate_image",
            step_index=0,
            total_steps=3,
            approval_type=ApprovalType.CHOOSE_ONE,
            options=[
                GeneratedOption(id="opt_1", type="image"),
                GeneratedOption(id="opt_2", type="image"),
            ],
            context={},
        )
        qm.add_approval_item(item)
        
        # Approve with selected option
        decision = ApprovalDecision(
            item_id="item_1",
            approved=True,
            selected_option_id="opt_2",
        )
        result = await qm.submit_decision(decision)
        
        assert result["status"] == "approved"
        assert result["selected"]["id"] == "opt_2"
        assert qm.get_status().awaiting_approval == 0

    @pytest.mark.asyncio
    async def test_submit_rejection_regenerate(self):
        """Test rejecting and requesting regeneration."""
        qm = QueueManager()
        
        item = ApprovalItem(
            id="item_1",
            asset_id="asset_1",
            asset_description="A fire dragon",
            step_id="portrait",
            step_name="generate_image",
            step_index=0,
            total_steps=3,
            approval_type=ApprovalType.ACCEPT_REJECT,
            options=[GeneratedOption(id="opt_1", type="image")],
            context={},
        )
        qm.add_approval_item(item)
        
        # Reject and regenerate
        decision = ApprovalDecision(
            item_id="item_1",
            approved=False,
            regenerate=True,
        )
        result = await qm.submit_decision(decision)
        
        assert result["status"] == "regenerating"
        assert result["attempt"] == 2
        
        # Item should still be in queue but with cleared options
        updated_item = qm.get_next_approval()
        assert updated_item is not None
        assert len(updated_item.options) == 0
        assert updated_item.attempt == 2

    def test_skip_item(self):
        """Test skipping an approval item."""
        qm = QueueManager()
        
        # Add asset first
        asset = Asset(id="asset_1", input_description="A fire dragon")
        qm.add_assets([asset])
        
        item = ApprovalItem(
            id="item_1",
            asset_id="asset_1",
            asset_description="A fire dragon",
            step_id="portrait",
            step_name="generate_image",
            step_index=0,
            total_steps=3,
            approval_type=ApprovalType.CHOOSE_ONE,
            options=[],
            context={},
        )
        qm.add_approval_item(item)
        
        result = qm.skip_item("item_1")
        
        assert result["status"] == "skipped"
        assert qm.get_status().awaiting_approval == 0

    def test_generating_tracking(self):
        """Test tracking generating items."""
        qm = QueueManager()
        
        # Start generating
        gen_id = qm.start_generating("asset_1", "portrait", "generate_image")
        
        items = qm.get_generating_items()
        assert len(items) == 1
        assert items[0].asset_id == "asset_1"
        
        # Update progress
        qm.update_progress(gen_id, 50.0)
        items = qm.get_generating_items()
        assert items[0].progress == 50.0
        
        # Finish generating
        qm.finish_generating(gen_id)
        items = qm.get_generating_items()
        assert len(items) == 0

    def test_start_pause_resume(self):
        """Test queue control operations."""
        qm = QueueManager()
        
        assert qm.get_status().is_running == False
        assert qm.get_status().is_paused == False
        
        qm.start()
        assert qm.get_status().is_running == True
        
        qm.pause()
        assert qm.get_status().is_paused == True
        
        qm.resume()
        assert qm.get_status().is_paused == False
        
        qm.stop()
        assert qm.get_status().is_running == False

    def test_clear(self):
        """Test clearing the queue."""
        qm = QueueManager()
        
        # Add some state
        qm.add_assets([Asset(id="a1", input_description="Test")])
        qm.add_approval_item(ApprovalItem(
            asset_id="a1",
            asset_description="Test",
            step_id="s1",
            step_name="test",
            step_index=0,
            total_steps=1,
            approval_type=ApprovalType.CHOOSE_ONE,
            options=[],
            context={},
        ))
        qm.start()
        
        # Clear
        qm.clear()
        status = qm.get_status()
        
        assert status.total_assets == 0
        assert status.awaiting_approval == 0
        assert status.is_running == False


class TestApprovalModels:
    """Tests for approval-related models."""

    def test_approval_item_creation(self):
        """Test creating an approval item."""
        item = ApprovalItem(
            asset_id="asset_1",
            asset_description="A fire dragon",
            step_id="portrait",
            step_name="generate_image",
            step_index=0,
            total_steps=3,
            approval_type=ApprovalType.CHOOSE_ONE,
            options=[],
            context={"key": "value"},
        )
        
        assert item.asset_id == "asset_1"
        assert item.approval_type == ApprovalType.CHOOSE_ONE
        assert item.attempt == 1
        assert item.max_attempts == 10

    def test_generated_option_image(self):
        """Test creating an image option."""
        opt = GeneratedOption(
            type="image",
            image_path="outputs/asset_1/portrait_0.png",
            image_data_url="data:image/png;base64,abc123",
            prompt_used="A fire dragon in fantasy style",
            generation_params={"width": 1024, "height": 1024},
        )
        
        assert opt.type == "image"
        assert opt.image_path is not None
        assert "width" in opt.generation_params

    def test_generated_option_text(self):
        """Test creating a text option."""
        opt = GeneratedOption(
            type="text",
            text_content="Pyraxion the Flame",
            prompt_used="Generate a name for: fire dragon",
        )
        
        assert opt.type == "text"
        assert opt.text_content == "Pyraxion the Flame"

    def test_queue_status_serialization(self):
        """Test QueueStatus can be serialized."""
        status = QueueStatus(
            total_assets=10,
            completed_assets=5,
            failed_assets=1,
            awaiting_approval=2,
            currently_generating=2,
            pending=0,
            is_running=True,
            is_paused=False,
        )
        
        data = status.model_dump()
        assert data["total_assets"] == 10
        assert data["completed_assets"] == 5
        assert data["is_running"] == True


class TestApprovalDecision:
    """Tests for approval decision handling."""

    def test_approve_with_selection(self):
        """Test approval decision with option selection."""
        decision = ApprovalDecision(
            item_id="item_1",
            approved=True,
            selected_option_id="opt_2",
        )
        
        assert decision.approved == True
        assert decision.selected_option_id == "opt_2"
        assert decision.regenerate == False

    def test_reject_with_regenerate(self):
        """Test rejection with regeneration request."""
        decision = ApprovalDecision(
            item_id="item_1",
            approved=False,
            regenerate=True,
        )
        
        assert decision.approved == False
        assert decision.regenerate == True
